"""WY integration uses the existing isolated real-PostgreSQL fixture."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'waitlist-payment'))
from lifecycle import Conflict, Lifecycle
from policy import select_next
from service import create_app as wy_app


class LocalSeats:
    def __init__(self, store):
        self.store = store

    def lookup(self, request_id, hold_id):
        return self.store.get_hold(request_id, hold_id)

    def confirm(self, request_id, hold_id):
        return self.store.transition(request_id, 'confirm', hold_id)


@pytest.fixture
def wy(db, store):
    result = Lifecycle(db, LocalSeats(store))
    result.initialize()
    return result


def test_exact_hold_lookup(client, store, make_due):
    hold = store.hold('A', 2, 'lookup')
    path = '/holds/' + hold['hold_id']
    assert client.get(path + '?request_id=lookup').json == hold
    assert client.get(path + '?request_id=other').status_code == 404
    make_due(hold['hold_id'])
    store.transition('lookup', 'expire', hold['hold_id'])
    assert client.get(path + '?request_id=lookup').json['hold_status'] == 'EXPIRED'


def test_lost_confirmation_response_recovers(wy, store, monkeypatch):
    hold = store.hold('A', 2, 'lost')
    payment = wy.start_payment('lost', hold['hold_id'], 'success', 'attempt-1')
    assert wy.start_payment('lost', hold['hold_id'], 'success', 'attempt-1')['payment_id'] == payment['payment_id']
    def lost_response(request_id, hold_id):
        store.transition(request_id, 'confirm', hold_id)
        raise requests.Timeout()
    monkeypatch.setattr(wy.seats, 'confirm', lost_response)
    with pytest.raises(requests.Timeout):
        wy.reconcile(payment['payment_id'])
    restarted = Lifecycle(wy.db, LocalSeats(store))
    assert restarted.reconcile(payment['payment_id'])['status'] == 'confirmed'
    assert all(s['state'] == 'CONFIRMED' for s in store.get_hold('lost', hold['hold_id'])['seats'])


def test_decline_allows_new_attempt_without_extending_deadline(wy, store):
    hold = store.hold('A', 1, 'decline')
    first = wy.start_payment('decline', hold['hold_id'], 'decline', 'one')
    assert wy.reconcile(first['payment_id'])['status'] == 'failed'
    with pytest.raises(Conflict):
        wy.start_payment('decline', hold['hold_id'], 'success', 'one')
    second = wy.start_payment('decline', hold['hold_id'], 'success', 'two')
    assert store.get_hold('decline', hold['hold_id'])['hold_expiry'] == hold['hold_expiry']
    assert wy.reconcile(second['payment_id'])['status'] == 'confirmed'


def test_expiry_event_is_durable_deduplicated_and_stale_safe(wy, store, make_due):
    old = store.hold('A', 2, 'expired')
    payment = wy.start_payment('expired', old['hold_id'], 'success', 'one')
    make_due(old['hold_id'])
    store.transition('expired', 'expire', old['hold_id'])
    new = store.hold('A', 2, 'expired', reoffer_key='two')
    event = {'event_id': str(uuid4()), 'hold_id': old['hold_id'], 'request_id': 'expired'}
    client = wy_app(wy).test_client()
    assert client.post('/notify/expired', json=event).json == {'success': True}
    assert client.post('/notify/expired', json=event).status_code == 200
    assert client.post('/notify/expired', json=dict(event, request_id='different')).status_code == 409
    Lifecycle(wy.db, LocalSeats(store)).recover()
    assert wy.reconcile(payment['payment_id'])['status'] == 'expired'
    assert store.get_hold('expired', new['hold_id'])['hold_status'] == 'ACTIVE'
    with wy.db.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM wy_expiry_events').fetchone()['n'] == 1
        assert conn.execute('SELECT processed_at FROM wy_expiry_events').fetchone()['processed_at']


def test_timeout_stays_pending_and_prevents_second_attempt(wy, store):
    hold = store.hold('A', 1, 'timeout')
    payment = wy.start_payment('timeout', hold['hold_id'], 'timeout', 'one')
    assert wy.reconcile(payment['payment_id'])['status'] == 'pending'
    with pytest.raises(Conflict):
        wy.start_payment('timeout', hold['hold_id'], 'success', 'two')


def test_waitlist_policy():
    initial = [{'request_id': 'small', 'party_size': 1, 'batch_order': 1},
               {'request_id': 'later', 'party_size': 4, 'batch_order': 2},
               {'request_id': 'large', 'party_size': 4, 'batch_order': 1}]
    late = [{'request_id': 'old', 'party_size': 4, 'arrival_order': 1},
            {'request_id': 'young', 'party_size': 1, 'arrival_order': 2}]
    assert select_next(initial, late, {1, 4})['request_id'] == 'large'
    assert select_next(initial, late, {1})['request_id'] == 'small'
    assert select_next([], late, {1}) is None
    assert select_next([], late, {4})['request_id'] == 'old'


def test_confirmation_loses_race_after_active_lookup(wy, store, make_due, monkeypatch):
    from store import StoreError
    hold = store.hold('A', 2, 'race')
    payment = wy.start_payment('race', hold['hold_id'], 'success', 'one')
    def late_confirm(request_id, hold_id):
        make_due(hold_id)
        try:
            return store.transition(request_id, 'confirm', hold_id)
        except StoreError as exc:
            response = requests.Response()
            response.status_code = exc.status
            raise requests.HTTPError(response=response) from exc
    monkeypatch.setattr(wy.seats, 'confirm', late_confirm)
    assert wy.reconcile(payment['payment_id'])['status'] == 'expired'
    assert store.get_hold('race', hold['hold_id'])['hold_status'] == 'EXPIRED'


def test_concurrent_duplicate_payment_intents(wy, store):
    from concurrent.futures import ThreadPoolExecutor
    hold = store.hold('A', 1, 'duplicate-payment')
    def start(_):
        return wy.start_payment('duplicate-payment', hold['hold_id'], 'success', 'same')['payment_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(start, range(4)))
    assert len(set(results)) == 1


def test_payment_http_contract(wy, store):
    hold = store.hold('A', 1, 'http-payment')
    client = wy_app(wy).test_client()
    payload = dict(request_id='http-payment', hold_id=hold['hold_id'], outcome='success', attempt_key='one')
    response = client.post('/payments', json=payload)
    assert response.status_code == 200
    assert client.post('/payments', json=payload).json == response.json
    assert client.get('/payments/' + response.json['payment_id']).json == {'status': 'pending'}
    assert client.post('/payments', json=dict(payload, outcome='decline')).status_code == 409
    assert client.post('/payments', json={}).status_code == 400
