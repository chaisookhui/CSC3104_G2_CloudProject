"""Durable mock checkout orchestration. Only SeatStore writes seat ownership."""
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import requests
from psycopg.types.json import Jsonb


class Conflict(ValueError):
    pass


class NotFound(Exception):
    pass


class DependencyError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class Deferred(Exception):
    """Safe work that cannot progress yet; schedule without consuming retry budget."""


def identifier(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f'Invalid {name}')
    return value


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Expected timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return result


def validate_hold(data, request_id, hold_id):
    """Also validate adapters used without HTTP; dependency failures are not user errors."""
    try:
        if not isinstance(data, dict) or data.get('success') is not True:
            raise ValueError('Missing hold result')
        if data['request_id'] != request_id or UUID(str(data['hold_id'])) != UUID(str(hold_id)):
            raise ValueError('Wrong hold identity')
        state = data['hold_status']
        if state not in ('ACTIVE', 'CONFIRMED', 'EXPIRED', 'CANCELLED'):
            raise ValueError('Unknown hold state')
        seats = data['seats']
        if not isinstance(seats, list) or not 1 <= len(seats) <= 4:
            raise ValueError('Missing seats')
        seen = set()
        for seat in seats:
            sid = identifier(seat['seat_id'], 'seat_id')
            identifier(seat['section'], 'section')
            if (sid in seen or type(seat['row']) is not int or seat['row']<1 or
                    type(seat['position_in_row']) is not int or not 1<=seat['position_in_row']<=10):
                raise ValueError('Invalid seats')
            seen.add(sid)
            if state in ('ACTIVE', 'CONFIRMED'):
                if (seat['held_by_request_id'] != request_id or
                        str(seat['hold_id']) != str(hold_id) or
                        seat['state'] != ('HELD' if state == 'ACTIVE' else 'CONFIRMED')):
                    raise ValueError('Wrong seat ownership')
        positions = sorted(s['position_in_row'] for s in seats)
        if (len({s['section'] for s in seats})!=1 or len({s['row'] for s in seats})!=1 or
                positions!=list(range(positions[0],positions[0]+len(seats)))):
            raise ValueError('Nonadjacent party')
        if state == 'ACTIVE':
            timestamp(data['hold_expiry'])
        elif data.get('hold_expiry') is not None:
            timestamp(data['hold_expiry'])
        return data
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise DependencyError('Invalid SeatStore hold response') from exc


class SeatClient:
    def __init__(self, url, timeout=5, cancel_path='', session=None):
        self.url, self.timeout, self.cancel_path = url.rstrip('/'), timeout, cancel_path
        self.session = session or requests

    def _call(self, method, path, **kwargs):
        try:
            response = self.session.request(method, self.url + path, timeout=(3, self.timeout),
                                            allow_redirects=False, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Expected object')
            return data
        except requests.HTTPError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise DependencyError('SeatStore response unavailable or malformed') from exc

    def lookup(self, request_id, hold_id):
        return validate_hold(self._call('GET', '/holds/' + str(hold_id),
                             params={'request_id': request_id}), request_id, hold_id)

    def confirm(self, request_id, hold_id):
        return validate_hold(self._call('POST', '/seats/confirm',
            json={'request_id': request_id, 'hold_id': str(hold_id)}), request_id, hold_id)

    def cancel(self, request_id, hold_id):
        if not self.cancel_path:
            raise DependencyError('SeatStore cancellation is not configured', retryable=False)
        return validate_hold(self._call('POST', self.cancel_path,
            json={'request_id': request_id, 'hold_id': str(hold_id)}), request_id, hold_id)


class Lifecycle:
    def __init__(self, database, seats, status_url='', sender=None):
        self.db, self.seats = database, seats
        self.status_url, self.sender = status_url, sender or requests.post

    def initialize(self):
        root = Path(__file__).parent
        migrations = [('001_baseline.sql', root / 'schema.sql')]
        migrations += [(p.name, p) for p in sorted((root / 'migrations').glob('*.sql'))]
        with self.db.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(3104004)')
            conn.execute('CREATE TABLE IF NOT EXISTS wy_schema_migrations '
                         '(name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
            for name, path in migrations:
                source = path.read_text(encoding='utf-8')
                checksum = hashlib.sha256(source.encode()).hexdigest()
                row = conn.execute('SELECT checksum FROM wy_schema_migrations WHERE name=%s', (name,)).fetchone()
                if row:
                    if row['checksum'] != checksum:
                        raise ValueError('Applied payment migration changed: ' + name)
                    continue
                conn.execute(source)
                conn.execute('INSERT INTO wy_schema_migrations VALUES (%s,%s)', (name, checksum))

    def ready(self):
        with self.db.connect() as conn:
            names = {r['name'] for r in conn.execute('SELECT name FROM wy_schema_migrations').fetchall()}
            expected = {'001_baseline.sql'} | {p.name for p in Path(__file__).with_name('migrations').glob('*.sql')}
            if not expected <= names:
                raise DependencyError('Run payment init-db before serving')
            return {r['state']: r['n'] for r in conn.execute(
                'SELECT state,count(*) AS n FROM wy_work GROUP BY state').fetchall()}

    @staticmethod
    def _lock(conn, hold_id):
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('wy:' + str(hold_id),))

    @staticmethod
    def _enqueue(conn, work_id, kind, payload):
        conn.execute('INSERT INTO wy_work(work_id,kind,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                     (work_id, kind, Jsonb(payload)))

    def _lookup(self, request_id, hold_id):
        try:
            data = self.seats.lookup(request_id, hold_id)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 503
            if code == 404:
                raise NotFound('Hold not found for this request') from exc
            raise DependencyError(f'SeatStore lookup HTTP {code}', retryable=code >= 500 or code in (408,429)) from exc
        return validate_hold(data, request_id, hold_id)

    @staticmethod
    def _replay(row, request_id, field, value):
        if row['request_id'] != request_id or row[field] != value:
            raise Conflict('Idempotency key already has different input')
        return row

    def start_payment(self, request_id, hold_id, outcome, attempt_key):
        hold_id = UUID(str(hold_id))
        identifier(request_id, 'request_id')
        identifier(attempt_key, 'attempt_key')
        if outcome not in ('success', 'decline', 'timeout'):
            raise ValueError('Invalid mock outcome')
        # Replays use committed local state even while SeatStore is unavailable.
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM wy_payments WHERE hold_id=%s AND attempt_key=%s',
                               (hold_id, attempt_key)).fetchone()
        if row:
            return self._replay(row, request_id, 'outcome', outcome)
        data = self._lookup(request_id, hold_id)
        if data['hold_status'] != 'ACTIVE':
            raise Conflict('Hold is not eligible for a new payment; retrieve checkout status')
        with self.db.connect() as conn:
            self._lock(conn, hold_id)
            row = conn.execute('SELECT * FROM wy_payments WHERE hold_id=%s AND attempt_key=%s',
                               (hold_id, attempt_key)).fetchone()
            if row:
                return self._replay(row, request_id, 'outcome', outcome)
            if conn.execute('SELECT clock_timestamp()>=%s AS elapsed',
                            (timestamp(data['hold_expiry']),)).fetchone()['elapsed']:
                raise Conflict('Hold deadline elapsed')
            if conn.execute('SELECT 1 FROM wy_cancellations WHERE hold_id=%s', (hold_id,)).fetchone():
                raise Conflict('Checkout cancellation already requested')
            if conn.execute("SELECT 1 FROM wy_payments WHERE hold_id=%s AND attempt_status='pending'", (hold_id,)).fetchone():
                raise Conflict('Reconcile pending payment before another attempt')
            checkout = conn.execute('SELECT hold_status FROM wy_checkouts WHERE hold_id=%s', (hold_id,)).fetchone()
            if checkout and checkout['hold_status'] != 'ACTIVE':
                raise Conflict('Checkout is closed')
            row = conn.execute('INSERT INTO wy_payments(payment_id,hold_id,attempt_key,request_id,outcome,status,attempt_status) '
                "VALUES (%s,%s,%s,%s,%s,'pending','pending') RETURNING *",
                (uuid4(), hold_id, attempt_key, request_id, outcome)).fetchone()
            self._observe(conn, data)
            self._enqueue(conn, 'payment:' + str(row['payment_id']), 'payment', {'payment_id': str(row['payment_id'])})
            self._enqueue(conn, 'checkout:' + str(hold_id), 'checkout', {'request_id': request_id, 'hold_id': str(hold_id)})
            return row

    def start_cancel(self, request_id, hold_id, action_key):
        hold_id = UUID(str(hold_id))
        identifier(request_id, 'request_id')
        identifier(action_key, 'action_key')
        with self.db.connect() as conn:
            previous = conn.execute('SELECT * FROM wy_cancellations WHERE hold_id=%s', (hold_id,)).fetchone()
        if previous:
            return self._replay(previous, request_id, 'action_key', action_key)
        data = self._lookup(request_id, hold_id)
        with self.db.connect() as conn:
            self._lock(conn, hold_id)
            previous = conn.execute('SELECT * FROM wy_cancellations WHERE hold_id=%s', (hold_id,)).fetchone()
            if previous:
                return self._replay(previous, request_id, 'action_key', action_key)
            status = {'ACTIVE': 'pending', 'CONFIRMED': 'confirmed', 'EXPIRED': 'expired', 'CANCELLED': 'cancelled'}[data['hold_status']]
            row = conn.execute('INSERT INTO wy_cancellations(action_id,hold_id,request_id,action_key,status) '
                'VALUES (%s,%s,%s,%s,%s) RETURNING *', (uuid4(), hold_id, request_id, action_key, status)).fetchone()
            self._observe(conn, data)
            self._enqueue(conn, 'cancel:' + str(row['action_id']), 'cancel', {'action_id': str(row['action_id'])})
            return row

    def _observe(self, conn, data):
        """Monotone booking projection and notification, committed together."""
        hold_id, state = UUID(data['hold_id']), data['hold_status']
        self._lock(conn, hold_id)
        old = conn.execute('SELECT * FROM wy_checkouts WHERE hold_id=%s', (hold_id,)).fetchone()
        if old and old['request_id'] != data['request_id']:
            raise DependencyError('Hold ownership changed', retryable=False)
        if (old and state=='ACTIVE' and old['original_expiry'] is not None and
                timestamp(data['hold_expiry'])!=old['original_expiry']):
            raise DependencyError('Original hold deadline changed', retryable=False)
        if old and old['hold_status'] != 'ACTIVE':
            if state != 'ACTIVE' and state != old['hold_status']:
                raise DependencyError('Conflicting terminal hold state', retryable=False)
            data, state = old['snapshot'], old['hold_status']
        conn.execute('INSERT INTO wy_checkouts(hold_id,request_id,hold_status,snapshot,original_expiry) VALUES (%s,%s,%s,%s,%s) '
            'ON CONFLICT (hold_id) DO UPDATE SET hold_status=EXCLUDED.hold_status,snapshot=EXCLUDED.snapshot,'
            'original_expiry=COALESCE(wy_checkouts.original_expiry,EXCLUDED.original_expiry),updated_at=clock_timestamp()',
            (hold_id, data['request_id'], state, Jsonb(data),timestamp(data['hold_expiry']) if data.get('hold_expiry') else None))
        if state != 'ACTIVE':
            # Legacy status remains booking projection; attempt_status is independent.
            conn.execute("UPDATE wy_payments SET status=%s,attempt_status=CASE "
                "WHEN attempt_status!='pending' THEN attempt_status "
                "WHEN outcome='decline' THEN 'declined' "
                "WHEN outcome='success' AND %s='CONFIRMED' THEN 'succeeded' ELSE 'closed' END,updated_at=clock_timestamp() WHERE hold_id=%s",
                (state.lower(), state, hold_id))
            conn.execute('UPDATE wy_cancellations SET status=%s WHERE hold_id=%s', (state.lower(), hold_id))
            event_id = uuid5(NAMESPACE_URL, f'checkout:{hold_id}:{state}')
            payload = {'version': 1, 'type': 'checkout.' + state.lower(), 'event_id': str(event_id),
                       'request_id': data['request_id'], 'hold_id': str(hold_id), 'hold_status': state}
            conn.execute('INSERT INTO wy_notifications(event_id,payload) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                         (event_id, Jsonb(payload)))
            self._enqueue(conn, 'notify:' + str(event_id), 'notification', payload)
        return data

    def reconcile(self, payment_id):
        payment_id = UUID(str(payment_id))
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM wy_payments WHERE payment_id=%s', (payment_id,)).fetchone()
            if not row:
                raise NotFound('Unknown payment')
            cancelled = conn.execute('SELECT 1 FROM wy_cancellations WHERE hold_id=%s', (row['hold_id'],)).fetchone()
        data = self._lookup(row['request_id'], row['hold_id'])
        if data['hold_status'] == 'ACTIVE' and row['outcome'] == 'success' and row['attempt_status'] == 'pending' and not cancelled:
            try:
                data = validate_hold(self.seats.confirm(row['request_id'], row['hold_id']), row['request_id'], row['hold_id'])
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 409:
                    raise
                data = self._lookup(row['request_id'], row['hold_id'])
        with self.db.connect() as conn:
            self._lock(conn, row['hold_id'])
            current = self._observe(conn, data)
            if current['hold_status'] == 'ACTIVE' and row['outcome'] == 'decline':
                conn.execute("UPDATE wy_payments SET status='failed',attempt_status='declined',updated_at=clock_timestamp() "
                             "WHERE payment_id=%s AND attempt_status='pending'", (payment_id,))
            return conn.execute('SELECT * FROM wy_payments WHERE payment_id=%s', (payment_id,)).fetchone()

    def reconcile_cancel(self, action_id):
        with self.db.connect() as conn:
            action = conn.execute('SELECT * FROM wy_cancellations WHERE action_id=%s', (UUID(str(action_id)),)).fetchone()
        if not action:
            raise NotFound('Unknown cancellation')
        data = self._lookup(action['request_id'], action['hold_id'])
        if data['hold_status'] == 'ACTIVE':
            try:
                data = validate_hold(self.seats.cancel(action['request_id'], action['hold_id']), action['request_id'], action['hold_id'])
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code not in (404,405,409):
                    raise
                if exc.response.status_code in (404,405):
                    raise DependencyError('SeatStore cancellation endpoint is unsupported', retryable=False) from exc
                data = self._lookup(action['request_id'], action['hold_id'])
        with self.db.connect() as conn:
            self._observe(conn, data)
        if data['hold_status'] == 'ACTIVE':
            raise Deferred('Cancellation not yet resolved by SeatStore')
        return data

    def checkout(self, request_id, hold_id, refresh=True):
        identifier(request_id, 'request_id')
        hold_id = UUID(str(hold_id))
        if refresh:
            data = self._lookup(request_id, hold_id)
            with self.db.connect() as conn:
                self._observe(conn, data)
        with self.db.connect() as conn:
            row = conn.execute('SELECT *,clock_timestamp() AS observed_now FROM wy_checkouts WHERE hold_id=%s AND request_id=%s', (hold_id, request_id)).fetchone()
            if not row:
                raise NotFound('Unknown checkout')
            attempts = conn.execute('SELECT payment_id,outcome,attempt_status FROM wy_payments WHERE hold_id=%s ORDER BY created_at', (hold_id,)).fetchall()
            action = conn.execute('SELECT * FROM wy_cancellations WHERE hold_id=%s', (hold_id,)).fetchone()
            work = conn.execute("SELECT state,last_error FROM wy_work WHERE work_id=%s", ('cancel:' + str(action['action_id']),)).fetchone() if action else None
        snapshot = row['snapshot']
        eligible = snapshot['hold_status'] == 'ACTIVE' and timestamp(snapshot['hold_expiry']) > row['observed_now']
        return {'request_id': request_id, 'hold_id': str(hold_id), 'booking_status': row['hold_status'].lower(),
                'booking_reference': str(hold_id) if row['hold_status']=='CONFIRMED' else None,
                'hold_expiry': snapshot.get('hold_expiry'), 'seats': snapshot['seats'],
                'original_hold_expiry': row['original_expiry'],
                'payment_attempts': attempts, 'cancellation': dict(action, recovery=work) if action else None,
                'can_pay': eligible and not action and not any(a['attempt_status']=='pending' for a in attempts),
                'can_cancel': eligible and not action, 'rejoin_owner': 'admission',
                'observed_at': row['updated_at'], 'source': 'seat-store' if refresh else 'cached'}

    def payment(self, payment_id):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM wy_payments WHERE payment_id=%s', (UUID(str(payment_id)),)).fetchone()
        if not row:
            raise NotFound('Unknown payment')
        return row

    def cancellation(self, action_id):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM wy_cancellations WHERE action_id=%s', (UUID(str(action_id)),)).fetchone()
            if not row:
                raise NotFound('Unknown cancellation')
            work = conn.execute('SELECT state,last_error,attempts FROM wy_work WHERE work_id=%s',
                                ('cancel:' + str(row['action_id']),)).fetchone()
        return dict(row, recovery=work)

    def work_status(self):
        with self.db.connect() as conn:
            return conn.execute('SELECT work_id,kind,state,attempts,last_error,available_at,updated_at '
                                "FROM wy_work WHERE state!='DONE' ORDER BY available_at LIMIT 100").fetchall()

    def receive_expiry(self, payload):
        return self.receive_event(payload, expired_only=True)

    def receive_event(self, payload, expired_only=False):
        if not isinstance(payload, dict):
            raise ValueError('Expected event object')
        try:
            event_id, hold_id = UUID(str(payload['event_id'])), UUID(str(payload['hold_id']))
            request_id = identifier(payload['request_id'], 'request_id')
        except KeyError as exc:
            raise ValueError('Missing event identity') from exc
        kind = payload.get('type', 'hold.expired')
        if kind not in ('hold.expired','hold.cancelled','hold.confirmed') or (expired_only and kind!='hold.expired'):
            raise ValueError('Unsupported hold event')
        if type(payload.get('version', 1)) is not int or payload.get('version', 1) != 1:
            raise ValueError('Unsupported event version')
        if 'section' in payload:
            identifier(payload['section'], 'section')
        if 'seats' in payload:
            seats = payload['seats']
            if not isinstance(seats,list) or not 1 <= len(seats) <= 4:
                raise ValueError('Invalid event seats')
            for seat in seats:
                identifier(seat, 'seat_id')
            if len(set(seats)) != len(seats):
                raise ValueError('Duplicate event seats')
        for key in ('expired_at','cancelled_at'):
            if key in payload:
                timestamp(payload[key])
        with self.db.connect() as conn:
            conn.execute('INSERT INTO wy_expiry_events(event_id,hold_id,request_id,payload) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (event_id, hold_id, request_id, Jsonb(payload)))
            old = conn.execute('SELECT payload FROM wy_expiry_events WHERE event_id=%s', (event_id,)).fetchone()
            if old['payload'] != payload:
                raise Conflict('Event ID reused with different payload')
            self._enqueue(conn, 'event:' + str(event_id), 'event', {'event_id': str(event_id)})
        return {'success': True}

    def _event(self, event_id):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM wy_expiry_events WHERE event_id=%s', (UUID(event_id),)).fetchone()
        data = self._lookup(row['request_id'], row['hold_id'])
        expected = row['payload'].get('type','hold.expired').split('.')[-1].upper()
        if data['hold_status'] == 'ACTIVE':
            raise Deferred('Hold transition not visible yet')
        if data['hold_status'] != expected:
            raise DependencyError('Event disagrees with authoritative hold state', retryable=False)
        if ('section' in row['payload'] and any(s['section']!=row['payload']['section'] for s in data['seats'])) or (
            'seats' in row['payload'] and set(row['payload']['seats'])!={s['seat_id'] for s in data['seats']}):
            raise DependencyError('Event ownership metadata mismatch', retryable=False)
        with self.db.connect() as conn:
            self._observe(conn, data)
            conn.execute('UPDATE wy_expiry_events SET processed_at=clock_timestamp() WHERE event_id=%s', (row['event_id'],))

    def _claim(self):
        token = uuid4()
        with self.db.connect() as conn:
            row = conn.execute("""UPDATE wy_work SET state='IN_PROGRESS',token=%s,
                lease_until=clock_timestamp()+INTERVAL '30 seconds',attempts=attempts+1,updated_at=clock_timestamp()
                WHERE work_id=(SELECT work_id FROM wy_work WHERE
                (state='READY' AND available_at<=clock_timestamp()) OR
                (state='IN_PROGRESS' AND lease_until<=clock_timestamp())
                ORDER BY available_at,work_id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *""", (token,)).fetchone()
        return row

    def _finish(self, work, state, error=None, delay=0, failures=None):
        with self.db.connect() as conn:
            return conn.execute("UPDATE wy_work SET state=%s,last_error=%s,failures=COALESCE(%s,failures),token=NULL,lease_until=NULL,"
                "available_at=clock_timestamp()+%s*INTERVAL '1 second',updated_at=clock_timestamp() "
                "WHERE work_id=%s AND token=%s AND lease_until>clock_timestamp()",
                (state,error,failures,delay,work['work_id'],work['token'])).rowcount == 1

    def retry_work(self, work_id):
        with self.db.connect() as conn:
            row = conn.execute("UPDATE wy_work SET state='READY',attempts=0,failures=0,last_error=NULL,available_at=clock_timestamp(),"
                "token=NULL,lease_until=NULL WHERE work_id=%s AND state='BLOCKED' RETURNING work_id", (work_id,)).fetchone()
        if not row:
            raise Conflict('Only blocked work can be explicitly retried')
        return row

    def recover(self, limit=100, max_attempts=10, stop=None):
        """Short atomic claims; HTTP outside transactions. Poison work cannot starve others."""
        processed = 0
        for _ in range(limit):
            if stop is not None and stop.is_set():
                break
            work = self._claim()
            if not work:
                break
            p = work['payload']
            try:
                if work['kind']=='payment':
                    row = self.reconcile(p['payment_id'])
                    if row['attempt_status']=='pending':
                        raise Deferred('Payment awaits authoritative resolution')
                elif work['kind']=='cancel':
                    self.reconcile_cancel(p['action_id'])
                elif work['kind']=='event':
                    self._event(p['event_id'])
                elif work['kind']=='checkout':
                    data = self.checkout(p['request_id'],p['hold_id'])
                    if data['booking_status']=='active':
                        raise Deferred('Checkout remains active')
                else:
                    if not self.status_url:
                        raise Deferred('PAYMENT_STATUS_URL is not configured')
                    response = self.sender(self.status_url,json=p,headers={'Idempotency-Key':p['event_id']},
                                           timeout=(3,5),allow_redirects=False)
                    if not 200 <= response.status_code < 300:
                        raise DependencyError('Checkout notification not acknowledged')
                    with self.db.connect() as conn:
                        conn.execute('UPDATE wy_notifications SET delivered_at=clock_timestamp() WHERE event_id=%s', (UUID(p['event_id']),))
            except Deferred as exc:
                self._finish(work,'READY',str(exc),delay=5 if work['kind']!='notification' else 30)
            except (DependencyError,requests.RequestException,NotFound) as exc:
                retryable = not isinstance(exc,NotFound) and getattr(exc,'retryable',True)
                if isinstance(exc,requests.HTTPError) and exc.response is not None:
                    retryable = exc.response.status_code >= 500 or exc.response.status_code in (408,429)
                failures = work['failures'] + 1
                state = 'READY' if retryable and failures<max_attempts else 'BLOCKED'
                # Never store exception text from HTTP/database libraries (may contain secrets).
                reason = str(exc) if isinstance(exc,(DependencyError,NotFound)) else type(exc).__name__
                self._finish(work,state,reason,delay=min(300,2**min(failures,8)),failures=failures)
                logging.getLogger(__name__).warning('Payment work=%s kind=%s state=%s reason=%s',
                    work['work_id'],work['kind'],state,reason)
            except (KeyError,TypeError,ValueError,AttributeError) as exc:
                self._finish(work,'BLOCKED','Invalid stored work: '+type(exc).__name__)
            else:
                self._finish(work,'DONE')
            processed += 1
        return processed
