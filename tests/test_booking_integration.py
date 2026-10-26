"""Five-service integration with real PostgreSQL and routed Flask HTTP contracts.

Run separately from module suites (legacy app/db names are process-local).
"""
import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for folder in ('seat-store', 'waitlist-payment', 'batch-dispatcher', 'services/waiting-room'):
    sys.path.insert(0, str(ROOT / 'src' / folder))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seat_api = load('seat_api_integration', 'src/seat-store/app.py')
waiting_api = load('waiting_api_integration', 'src/services/waiting-room/app.py')
dispatcher_api = load('dispatcher_api_integration', 'src/batch-dispatcher/app.py')
from db import Database
from lifecycle import DependencyError, Lifecycle, SeatClient
from service import create_app as payment_app
from state_store import StateStore
from queue_store import MemoryStore
from src.allocation.app import create_app as allocation_app
from src.allocation.job_store import JobStore
from src.allocation.worker import process_one
from src.allocation.seat_client import hold_seats


class Network:
    def __init__(self):
        self.apps = {}
        self.lose_path = None

    def request(self, method, url, json=None, params=None, headers=None, **kwargs):
        parts = urlsplit(url)
        path = parts.path + ('?' + urlencode(params) if params else '')
        with self.apps[parts.port].test_client() as client:
            reply = client.open(path, method=method, json=json, headers=headers or {})
        response = requests.Response()
        response.status_code = reply.status_code
        response._content = reply.data
        response.headers.update(reply.headers)
        if self.lose_path == parts.path:
            self.lose_path = None
            raise requests.Timeout('Response lost after commit')
        return response


@pytest.fixture
def system(monkeypatch):
    dsn = os.getenv('TEST_DATABASE_URL')
    if not dsn or not conninfo_to_dict(dsn).get('dbname', '').endswith('_test'):
        pytest.fail('Set TEST_DATABASE_URL to a dedicated PostgreSQL URI ending in _test')
    name = 'flow_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    scoped = dsn + ('&' if '?' in dsn else '?') + urlencode({'options': '-c search_path=' + name}, quote_via=quote)
    try:
        database = Database(dsn, name)
        database.migrate()
        database.seed('dev')
        net = Network()
        net.apps[5003] = seat_api.create_app({'DATABASE_URL': dsn, 'DATABASE': database, 'TESTING': True})
        seats = net.apps[5003].extensions['seat_store']
        lifecycle = Lifecycle(database, SeatClient('http://127.0.0.1:5003', cancel_path='/seats/cancel', session=net))
        lifecycle.initialize()
        net.apps[5004] = payment_app(lifecycle)
        queue = MemoryStore()
        net.apps[5001] = waiting_api.create_app(queue, session=net)
        jobs = JobStore(scoped)
        jobs.initialize()
        net.apps[5002] = allocation_app(jobs)
        state = StateStore(scoped)
        net.apps[5005] = dispatcher_api.create_app(state, net)
        monkeypatch.setattr(requests, 'post', lambda url, **kw: net.request('POST', url, **kw))
        yield net, database, seats, lifecycle, queue, jobs, state
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))


def allocate(system, user='user', section='D', size=2):
    net, db, seats, lifecycle, queue, jobs, state = system
    client = net.apps[5001].test_client()
    entry = client.post('/submit', json={'user_id': user, 'section': section, 'party_size': size}).json
    client.post('/sale/start')
    dispatcher = net.apps[5005].extensions['dispatcher']
    dispatcher.tick()
    while process_one(jobs, hold=hold_seats):
        pass
    return client, entry, dispatcher


def test_checkout_discovered_before_batch_sync_and_confirmed(system):
    net, db, seats, lifecycle, queue, jobs, state = system
    client, entry, dispatcher = allocate(system)
    rid = entry['request_id']
    assert queue.read()['requests'][rid]['status'] == 'ADMITTED'
    checkout = client.get('/requests/' + rid + '/checkout')
    assert checkout.status_code == 200
    hold_id = checkout.json['hold_id']
    assert checkout.json['booking_status'] == 'active'
    dispatcher.tick()
    assert client.get('/requests/' + rid).json['allocation']['hold_id'] == hold_id
    pay = net.apps[5004].test_client().post('/payments', json={
        'request_id': rid, 'hold_id': hold_id, 'outcome': 'success', 'attempt_key': 'pay-1'})
    assert pay.status_code == 200
    lifecycle.reconcile(pay.json['payment_id'])
    assert client.get('/requests/' + rid + '/checkout').json['booking_status'] == 'confirmed'
    assert hold_seats('D', 2, rid)['hold_expiry'] is None


def test_cancel_lost_response_recovers_and_exits(system):
    net, db, seats, lifecycle, queue, jobs, state = system
    client, entry, dispatcher = allocate(system)
    dispatcher.tick()
    rid = entry['request_id']
    path = '/requests/' + rid
    net.lose_path = '/checkouts/cancel'
    assert client.post(path + '/cancel', json={'action_key': 'cancel-1'}).status_code == 503
    cancel = client.post(path + '/cancel', json={'action_key': 'cancel-1'})
    assert cancel.status_code == 202
    # Failure before seat-store acknowledgement must remain recoverable.
    net.lose_path = '/seats/cancel'
    with pytest.raises(DependencyError):
        lifecycle.reconcile_cancel(cancel.json['action_id'])
    lifecycle.reconcile_cancel(cancel.json['action_id'])
    assert client.get(path + '/checkout').json['booking_status'] == 'cancelled'
    # Cancelling is an exit point: registering again returns the finished entry.
    assert client.post('/submit', json={'user_id': 'user', 'section': 'D', 'party_size': 2}).json['request_id'] == rid


def test_expired_and_unavailable_requests_exit(system):
    net, db, seats, lifecycle, queue, jobs, state = system
    client, entry, dispatcher = allocate(system)
    dispatcher.tick()
    path = '/requests/' + entry['request_id']
    held = client.get(path + '/checkout').json
    with db.connect() as conn:
        conn.execute("UPDATE holds SET hold_expiry=clock_timestamp()-INTERVAL '1 second' WHERE hold_id=%s", (held['hold_id'],))
    seats.expire_due()
    assert client.get(path + '/checkout').json['booking_status'] == 'expired'
    assert client.post('/submit', json={'user_id': 'user', 'section': 'D', 'party_size': 2}).json['request_id'] == entry['request_id']
    # A request with no fitting block in its section ends as UNAVAILABLE.
    for i, size in enumerate((4, 4, 2)):
        seats.hold('C', size, 'fill-' + str(i))
    failed = client.post('/submit', json={'user_id': 'no-fit', 'section': 'C', 'party_size': 1}).json
    dispatcher.tick()
    while process_one(jobs, hold=hold_seats):
        pass
    dispatcher.tick()
    rid = failed['request_id']
    assert client.get('/requests/' + rid).json['status'] == 'UNAVAILABLE'
    assert client.post('/submit', json={'user_id': 'no-fit', 'section': 'A', 'party_size': 1}).json['request_id'] == rid


def test_dispatcher_postgres_restart_after_accepted_submission(system):
    net, db, seats, lifecycle, queue, jobs, state = system
    net.lose_path = '/batches'
    client = net.apps[5001].test_client()
    entry = client.post('/submit', json={'user_id': 'restart', 'section': 'D', 'party_size': 1}).json
    client.post('/sale/start')
    saved = state.read()['active']
    assert saved['state'] == 'SUBMITTING'
    assert len(jobs.batch(saved['batch_id'])['jobs']) == 1
    token, value = state.claim()
    value['active']['retry_at'] = 0
    state.save(token, value, release=True)
    restarted = dispatcher_api.Dispatcher(StateStore(state.url), net)
    restarted.tick()
    process_one(jobs, hold=hold_seats)
    restarted.tick()
    assert state.read()['active'] is None
    assert state.read()['history'][0]['batch_id'] == saved['batch_id']
    assert client.get('/requests/' + entry['request_id'] + '/checkout').status_code == 200


def test_authenticated_payment_handoff_and_confirmation(system,monkeypatch):
    net,db,seats,lifecycle,queue,jobs,state=system
    token='integration-only-internal-token-32chars'
    monkeypatch.setenv('PAYMENT_API_TOKEN',token)
    net.apps[5004]=payment_app(lifecycle,api_token=token)
    net.apps[5001]=waiting_api.create_app(queue,session=net)
    client,entry,dispatcher=allocate(system,user='secured')
    checkout=client.get('/requests/'+entry['request_id']+'/checkout')
    assert checkout.status_code==200  # waiting-room forwards its internal token
    payload={'request_id':entry['request_id'],'hold_id':checkout.json['hold_id'],
             'outcome':'success','attempt_key':'secure-one'}
    payment=net.apps[5004].test_client()
    assert payment.post('/payments',json=payload).status_code==401
    reply=payment.post('/payments',json=payload,headers={'Authorization':'Bearer '+token})
    assert reply.status_code==200
    lifecycle.reconcile(reply.json['payment_id'])
    assert client.get('/requests/'+entry['request_id']+'/checkout').json['booking_status']=='confirmed'


def test_authenticated_seat_expiry_notification(system,monkeypatch):
    from workers import OutboxDispatcher
    net,db,seats,lifecycle,queue,jobs,state=system
    token='integration-only-internal-token-32chars'
    monkeypatch.setenv('PAYMENT_API_TOKEN',token)
    net.apps[5004]=payment_app(lifecycle,api_token=token)
    net.apps[5001]=waiting_api.create_app(queue,session=net)
    client,entry,dispatcher=allocate(system,user='secure-expiry')
    checkout=client.get('/requests/'+entry['request_id']+'/checkout').json
    with db.connect() as conn:
        conn.execute("UPDATE holds SET hold_expiry=clock_timestamp()-INTERVAL '1 second' WHERE hold_id=%s",(checkout['hold_id'],))
    seats.expire_due()
    callbacks=OutboxDispatcher(db,'http://127.0.0.1:5004',api_token=token,
                              sender=lambda url,**kw: net.request('POST',url,**kw))
    assert callbacks.deliver_one()
    lifecycle.recover()
    with db.connect() as conn:
        assert conn.execute('SELECT delivered_at FROM notification_outbox').fetchone()['delivered_at'] is not None
        assert conn.execute('SELECT processed_at FROM wy_expiry_events').fetchone()['processed_at'] is not None
    assert client.get('/requests/'+entry['request_id']+'/checkout').json['booking_status']=='expired'


def test_scoped_customer_checkout_with_real_seat_store(system,monkeypatch):
    from payment_security import CheckoutTokens
    net,db,seats,lifecycle,queue,jobs,state=system
    internal='integration-only-internal-token-32chars'
    key='integration-only-independent-signing-key'
    monkeypatch.setenv('PAYMENT_API_TOKEN',internal)
    net.apps[5004]=payment_app(lifecycle,api_token=internal,checkout_key=key)
    net.apps[5001]=waiting_api.create_app(queue,session=net)
    client,entry,dispatcher=allocate(system,user='alice')
    hold=client.get('/requests/'+entry['request_id']+'/checkout').json['hold_id']
    issuer=CheckoutTokens(key)
    alice={'Authorization':'Bearer '+issuer.issue('alice',entry['request_id'],hold)}
    bob={'Authorization':'Bearer '+issuer.issue('bob','other-request',uuid4())}
    payment=net.apps[5004].test_client()
    assert payment.get('/customer/checkout',headers=bob).status_code==404
    assert payment.post('/customer/payments',json={'attempt_key':'one','hold_id':hold},headers=bob).status_code==400
    reply=payment.post('/customer/payments',json={'attempt_key':'one'},headers=alice)
    assert reply.status_code==200
    assert payment.get('/customer/payments/'+reply.json['payment_id'],headers=bob).status_code==404
    lifecycle.recover()
    assert payment.get('/customer/checkout',headers=alice).json['booking_status']=='confirmed'
