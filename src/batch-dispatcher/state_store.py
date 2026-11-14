"""Fenced active progress and append-only history/receipts in the same database."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class StateStore:
    def __init__(self, url):
        self.url = url
        self.sqlite = url.startswith('sqlite:///')
        if self.sqlite:
            Path(url[10:]).parent.mkdir(parents=True, exist_ok=True)
        elif not url.startswith(('postgresql://', 'postgres://')):
            raise ValueError('Use PostgreSQL or a persistent sqlite:/// file')
        with self.transaction() as run:
            if not self.sqlite:
                # PostgreSQL IF NOT EXISTS alone does not serialize concurrent
                # first-start DDL from multiple Gunicorn processes/replicas.
                run('SELECT pg_advisory_xact_lock(3104006)')
            run('''CREATE TABLE IF NOT EXISTS dispatcher_state (
                id INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                token TEXT, lease_until DOUBLE PRECISION NOT NULL DEFAULT 0)''')
            run('INSERT INTO dispatcher_state(id,payload) VALUES (1,?) ON CONFLICT(id) DO NOTHING',
                (json.dumps({'active': None, 'history': [], 'events': {}}),))
            run('''CREATE TABLE IF NOT EXISTS dispatcher_history (
                batch_id TEXT PRIMARY KEY, position BIGINT NOT NULL UNIQUE, payload TEXT NOT NULL)''')
            run('''CREATE TABLE IF NOT EXISTS dispatcher_events (
                event_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, payload TEXT NOT NULL)''')
            self._load(run)

    @contextmanager
    def transaction(self):
        if self.sqlite:
            conn = sqlite3.connect(self.url[10:], timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
        else:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict
            from psycopg.rows import dict_row
            options = conninfo_to_dict(self.url).get('options', '')
            conn = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5,
                                   options=options + ' -c lock_timeout=5000 -c statement_timeout=15000')
        try:
            def run(sql, values=()):
                return conn.execute(sql if self.sqlite else sql.replace('?', '%s'), values)
            yield run
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _now(self, run):
        if self.sqlite:
            return time.time()
        return float(run('SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now').fetchone()['now'])

    @staticmethod
    def _append_history(run, batch):
        run('''INSERT INTO dispatcher_history(batch_id,position,payload)
            VALUES (?,(SELECT COALESCE(MAX(position),0)+1 FROM dispatcher_history),?)
            ON CONFLICT(batch_id) DO NOTHING''', (batch['batch_id'],json.dumps(batch)))
        previous = json.loads(run('SELECT payload FROM dispatcher_history WHERE batch_id=?',
                                  (batch['batch_id'],)).fetchone()['payload'])
        if previous != batch:
            raise ValueError('Conflicting completed batch history')

    @staticmethod
    def _put_event(run, event):
        run('''INSERT INTO dispatcher_events(event_id,batch_id,payload) VALUES (?,?,?)
            ON CONFLICT(event_id) DO NOTHING''', (event['event_id'],event['batch_id'],json.dumps(event)))
        previous = json.loads(run('SELECT payload FROM dispatcher_events WHERE event_id=?',
                                  (event['event_id'],)).fetchone()['payload'])
        if previous != event:
            raise ValueError('Conflicting event ID')

    def _normalize(self, run, state):
        """Move legacy inline records transactionally; repeated migration is safe.

        Normal progress writes only the active batch. Keeping empty legacy fields
        permits an old writer's append to be recovered on the next new operation.
        All methods serialize on the original dispatcher row, including hydration.
        """
        if state.get('history') or state.get('events'):
            for batch in state.get('history',[]): self._append_history(run,batch)
            for event in state.get('events',{}).values(): self._put_event(run,event)
            state['history']=[];state['events']={}
            run('UPDATE dispatcher_state SET payload=? WHERE id=1',(json.dumps(state),))
        return state

    def _load(self, run):
        suffix = '' if self.sqlite else ' FOR UPDATE'
        row = run('SELECT payload,token,lease_until FROM dispatcher_state WHERE id=1'+suffix).fetchone()
        return row, self._normalize(run,json.loads(row['payload']))

    def claim(self, seconds=60):
        token = str(uuid4())
        with self.transaction() as run:
            now = self._now(run)
            row = run('''UPDATE dispatcher_state SET token=?,lease_until=?
                WHERE id=1 AND (token IS NULL OR lease_until<=?) RETURNING payload''',
                (token, now + seconds, now)).fetchone()
            return (token, self._normalize(run,json.loads(row['payload']))) if row else None

    def read(self):
        with self.transaction() as run:
            _, state = self._load(run)
            state['history'] = [json.loads(row['payload']) for row in
                run('SELECT payload FROM dispatcher_history ORDER BY position').fetchall()]
            state['events'] = {row['event_id']:json.loads(row['payload']) for row in
                run('SELECT event_id,payload FROM dispatcher_events').fetchall()}
            return state

    def save(self, token, state, release=False):
        with self.transaction() as run:
            row, _ = self._load(run)
            if row['token'] != token or row['lease_until'] <= self._now(run):
                raise RuntimeError('Dispatcher lease lost; another worker will reconcile')
            for batch in state['history']: self._append_history(run,batch)
            hot = dict(state,history=[],events={})
            # Receipt rows are independent of stale worker snapshots. Progress,
            # completed history and the lease commit together under this fence.
            now = self._now(run)
            changed = run('''UPDATE dispatcher_state SET payload=?, token=?, lease_until=?
                WHERE id=1 AND token=? AND lease_until>?''',
                (json.dumps(hot), None if release else token, 0 if release else now + 60,
                 token, now)).rowcount
            if changed != 1:
                raise RuntimeError('Dispatcher lease lost; another worker will reconcile')
        # Clear staged appends only after commit; an ambiguous commit can retry
        # the identical batch without duplication or loss.
        state['history']=[];state['events']={}

    def record_event(self, event):
        with self.transaction() as run:
            _, state = self._load(run)
            previous = run('SELECT payload FROM dispatcher_events WHERE event_id=?',
                           (event['event_id'],)).fetchone()
            if previous:
                if json.loads(previous['payload']) != event:
                    raise ValueError('Conflicting event ID')
                return
            known = (state['active'] and state['active']['batch_id']==event['batch_id']) or run(
                'SELECT batch_id FROM dispatcher_history WHERE batch_id=?',(event['batch_id'],)).fetchone()
            if not known:
                raise ValueError('Unknown batch')
            self._put_event(run,event)
