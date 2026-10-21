"""Durable mock payment and expiry inbox. No seat writes or network under locks."""

from pathlib import Path
from uuid import UUID, uuid4

import requests
from psycopg.types.json import Jsonb


class Conflict(ValueError):
    pass


class SeatClient:
    def __init__(self, url, timeout=5):
        self.url, self.timeout = url.rstrip('/'), timeout

    def _call(self, method, path, **kwargs):
        response = requests.request(method, self.url + path, timeout=self.timeout,
                                    allow_redirects=False, **kwargs)
        response.raise_for_status()
        return response.json()

    def lookup(self, request_id, hold_id):
        return self._call('GET', '/holds/' + str(hold_id), params={'request_id': request_id})

    def confirm(self, request_id, hold_id):
        return self._call('POST', '/seats/confirm',
                          json={'request_id': request_id, 'hold_id': str(hold_id)})


class Lifecycle:
    def __init__(self, database, seats):
        self.db, self.seats = database, seats

    def initialize(self):
        with self.db.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(3104004)')
            conn.execute(Path(__file__).with_name('schema.sql').read_text())

    def start_payment(self, request_id, hold_id, outcome, attempt_key):
        """Persist one simulation per attempt; a decline permits a new keyed attempt."""
        hold_id = UUID(str(hold_id))
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
            raise ValueError('Invalid request_id')
        if outcome not in ('success', 'decline', 'timeout'):
            raise ValueError('Invalid mock outcome')
        if not isinstance(attempt_key, str) or not attempt_key.strip() or len(attempt_key) > 128:
            raise ValueError('Invalid attempt_key')
        # Verify ownership using authoritative storage before recording intent.
        self.seats.lookup(request_id, hold_id)
        with self.db.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('wy:'+str(hold_id),))
            row = conn.execute('SELECT * FROM wy_payments WHERE hold_id=%s AND attempt_key=%s',
                               (hold_id, attempt_key)).fetchone()
            if row is None:
                pending = conn.execute("SELECT 1 FROM wy_payments WHERE hold_id=%s AND status='pending'",
                                       (hold_id,)).fetchone()
                if pending:
                    raise Conflict('Reconcile the pending payment before starting another attempt')
                row = conn.execute('INSERT INTO wy_payments(payment_id,hold_id,attempt_key,request_id,outcome,status) '
                                   "VALUES (%s,%s,%s,%s,%s,'pending') RETURNING *",
                                   (uuid4(), hold_id, attempt_key, request_id, outcome)).fetchone()
            if row['request_id'] != request_id or row['outcome'] != outcome:
                raise Conflict('Hold already has a different payment simulation')
        return row

    def reconcile(self, payment_id):
        payment_id = UUID(str(payment_id))
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM wy_payments WHERE payment_id=%s', (payment_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown payment hold')
        hold_id = row['hold_id']
        authoritative = self.seats.lookup(row['request_id'], hold_id)
        status = authoritative['hold_status']
        if status == 'ACTIVE' and row['outcome'] == 'success':
            try:
                status = self.seats.confirm(row['request_id'], hold_id)['hold_status']
            except requests.HTTPError as exc:
                if exc.response.status_code != 409:
                    raise
                status = self.seats.lookup(row['request_id'], hold_id)['hold_status']
        local = {'CONFIRMED': 'confirmed', 'EXPIRED': 'expired',
                 'ACTIVE': 'failed' if row['outcome'] == 'decline' else 'pending'}[status]
        with self.db.connect() as conn:
            # Never let an older overlapping reconciliation undo a terminal result.
            conn.execute("UPDATE wy_payments SET status=%s, updated_at=clock_timestamp() "
                         "WHERE payment_id=%s AND status NOT IN ('confirmed','expired')", (local, payment_id))
            return conn.execute('SELECT * FROM wy_payments WHERE payment_id=%s', (payment_id,)).fetchone()

    def receive_expiry(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('Expected event object')
        event_id, hold_id = UUID(str(payload['event_id'])), UUID(str(payload['hold_id']))
        request_id = payload['request_id']
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError('Invalid request_id')
        with self.db.connect() as conn:
            conn.execute('INSERT INTO wy_expiry_events(event_id,hold_id,request_id,payload) '
                         'VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (event_id, hold_id, request_id, Jsonb(payload)))
            previous = conn.execute('SELECT payload FROM wy_expiry_events WHERE event_id=%s',
                                    (event_id,)).fetchone()
            if previous['payload'] != payload:
                raise Conflict('Event ID reused with different payload')
        return {'success': True}

    def recover(self):
        """Bounded scan; errors leave durable work pending for a later pass."""
        with self.db.connect() as conn:
            payments = conn.execute("SELECT payment_id FROM wy_payments WHERE status IN ('pending','failed') "
                                    'ORDER BY updated_at LIMIT 100').fetchall()
            events = conn.execute('SELECT * FROM wy_expiry_events WHERE processed_at IS NULL '
                                  'ORDER BY created_at LIMIT 100').fetchall()
        for row in payments:
            try:
                self.reconcile(row['payment_id'])
            except requests.RequestException:
                continue
        for event in events:
            try:
                state = self.seats.lookup(event['request_id'], event['hold_id'])
            except requests.RequestException:
                continue
            if state['hold_status'] != 'EXPIRED':
                continue
            with self.db.connect() as conn:
                conn.execute("UPDATE wy_payments SET status='expired',updated_at=clock_timestamp() "
                             "WHERE hold_id=%s AND status != 'confirmed'", (event['hold_id'],))
                conn.execute('UPDATE wy_expiry_events SET processed_at=clock_timestamp() WHERE event_id=%s',
                             (event['event_id'],))
