"""Durable dispatcher state. PostgreSQL for replicas; SQLite for one local host."""
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
            run('''CREATE TABLE IF NOT EXISTS dispatcher_state (
                id INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                token TEXT, lease_until DOUBLE PRECISION NOT NULL DEFAULT 0)''')
            run('INSERT INTO dispatcher_state(id,payload) VALUES (1,?) ON CONFLICT(id) DO NOTHING',
                (json.dumps({'active': None, 'history': [], 'events': {}}),))

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

    def claim(self, seconds=60):
        token = str(uuid4())
        with self.transaction() as run:
            now = self._now(run)
            row = run('''UPDATE dispatcher_state SET token=?,lease_until=?
                WHERE id=1 AND (token IS NULL OR lease_until<=?) RETURNING payload''',
                (token, now + seconds, now)).fetchone()
            return (token, json.loads(row['payload'])) if row else None

    def read(self):
        with self.transaction() as run:
            return json.loads(run('SELECT payload FROM dispatcher_state WHERE id=1').fetchone()['payload'])

    def save(self, token, state, release=False):
        with self.transaction() as run:
            # The worker owns progress; callback receipts can arrive concurrently.
            suffix = '' if self.sqlite else ' FOR UPDATE'
            row = run('SELECT payload FROM dispatcher_state WHERE id=1' + suffix).fetchone()
            state['events'] = json.loads(row['payload'])['events']
            now = self._now(run)
            changed = run('''UPDATE dispatcher_state SET payload=?, token=?, lease_until=?
                WHERE id=1 AND token=? AND lease_until>?''',
                (json.dumps(state), None if release else token, 0 if release else now + 60,
                 token, now)).rowcount
            if changed != 1:
                raise RuntimeError('Dispatcher lease lost; another worker will reconcile')

    def record_event(self, event):
        with self.transaction() as run:
            suffix = '' if self.sqlite else ' FOR UPDATE'
            row = run('SELECT payload FROM dispatcher_state WHERE id=1' + suffix).fetchone()
            state = json.loads(row['payload'])
            previous = state['events'].get(event['event_id'])
            if previous is not None:
                if previous != event:
                    raise ValueError('Conflicting event ID')
                return
            known = ([state['active']] if state['active'] else []) + state['history']
            if not any(b['batch_id'] == event['batch_id'] for b in known):
                raise ValueError('Unknown batch')
            state['events'][event['event_id']] = event
            run('UPDATE dispatcher_state SET payload=? WHERE id=1', (json.dumps(state),))
