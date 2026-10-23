from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from store import StoreError
from workers import OutboxDispatcher


def test_exact_hold_cancel_releases_once_and_delivers_event(client, store, db):
    held = store.hold('D', 4, 'cancel-me')
    payload = {'request_id': 'cancel-me', 'hold_id': held['hold_id']}
    first = client.post('/seats/cancel', json=payload)
    assert first.status_code == 200
    assert first.json['hold_status'] == 'CANCELLED'
    assert client.post('/seats/cancel', json=payload).json == first.json
    assert all(s['state'] == 'AVAILABLE' for s in store.list_seats('D'))
    calls = []

    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {'success': True}

    def send(url, **kwargs):
        calls.append((url, kwargs['json']))
        return Response()

    dispatcher = OutboxDispatcher(db, 'http://payment', sender=send)
    assert dispatcher.deliver_one()
    assert not dispatcher.deliver_one()
    assert calls[0][0] == 'http://payment/notify/holds'
    assert calls[0][1]['type'] == 'hold.cancelled'
    with pytest.raises(StoreError):
        store.transition('cancel-me', 'confirm', held['hold_id'])
    with pytest.raises(StoreError):
        store.hold('D', 4, 'cancel-me')
    replacement = store.hold('D', 4, 'replacement')
    assert store.transition('cancel-me', 'cancel', held['hold_id'])['hold_status'] == 'CANCELLED'
    assert store.get_hold('replacement', replacement['hold_id'])['hold_status'] == 'ACTIVE'


def test_cancel_requires_exact_identity_and_preserves_paid_seats(client, store):
    held = store.hold('A', 2, 'paid')
    assert client.post('/seats/cancel', json={'request_id': 'paid'}).status_code == 400
    assert client.post('/seats/cancel', json={'request_id': 'paid', 'hold_id': None}).status_code == 400
    assert client.post('/seats/cancel', json={'request_id': 'other', 'hold_id': held['hold_id']}).status_code == 404
    store.transition('paid', 'confirm', held['hold_id'])
    result = client.post('/seats/cancel', json={'request_id': 'paid', 'hold_id': held['hold_id']})
    assert result.json['hold_status'] == 'CONFIRMED'
    assert all(s['state'] == 'CONFIRMED' for s in result.json['seats'])


def test_cancel_after_deadline_is_expiry(store, make_due):
    held = store.hold('A', 2, 'late-cancel')
    make_due(held['hold_id'])
    assert store.transition('late-cancel', 'cancel', held['hold_id'])['hold_status'] == 'EXPIRED'


def test_confirm_cancel_race_never_releases_confirmed_seats(store, db):
    held = store.hold('A', 4, 'race')
    barrier = Barrier(2)

    def run(action):
        barrier.wait(timeout=5)
        try:
            return store.transition('race', action, held['hold_id'])['hold_status']
        except StoreError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ('confirm', 'cancel')))
    final = store.get_hold('race', held['hold_id'])
    expected = 'CONFIRMED' if final['hold_status'] == 'CONFIRMED' else 'AVAILABLE'
    assert all(s['state'] == expected for s in store.list_seats('A')[:4])
    with db.connect() as conn:
        count = conn.execute('SELECT count(*) AS n FROM notification_outbox').fetchone()['n']
    assert count == (1 if expected == 'AVAILABLE' else 0)


def test_upgrade_adds_d_without_changing_existing_booking(db):
    import hashlib
    from uuid import uuid4
    import psycopg
    from psycopg import sql
    from conftest import ROOT
    from db import Database
    from store import SeatStore

    name = 'upgrade_' + uuid4().hex
    with psycopg.connect(db.dsn, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    legacy = Database(db.dsn, name)
    try:
        source = (ROOT / 'database/migrations/001_initial.sql').read_text(encoding='utf-8')
        with legacy.connect() as conn:
            conn.execute(source)
            conn.execute('CREATE TABLE schema_migrations(name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
            conn.execute('INSERT INTO schema_migrations VALUES (%s,%s)',
                         ('001_initial.sql', hashlib.sha256(source.encode()).hexdigest()))
            for section, rows in (('A', 3), ('B', 2), ('C', 1)):
                conn.execute('INSERT INTO sections VALUES (%s,%s,10)', (section, rows))
                conn.execute('''INSERT INTO seats(seat_id,section,row,position_in_row)
                    SELECT %s || '-' || r || '-' || p, %s, r, p
                    FROM generate_series(1,%s) r CROSS JOIN generate_series(1,10) p''',
                    (section, section, rows))
        old = SeatStore(legacy).hold('A', 2, 'preserved')
        legacy.migrate()
        legacy.seed('dev')
        assert SeatStore(legacy).get_hold('preserved', old['hold_id']) == old
        assert len(SeatStore(legacy).list_seats('D')) == 10
        legacy.migrate()
        assert SeatStore(legacy).get_hold('preserved', old['hold_id']) == old
    finally:
        with psycopg.connect(db.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
