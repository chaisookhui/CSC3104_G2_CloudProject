import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
from uuid import UUID, uuid4
from unittest.mock import Mock

import psycopg
import pytest
import requests

from lifecycle import Conflict, DependencyError, Lifecycle, SeatClient, validate_hold
from service import create_app


class Seats:
    """Controlled remote hold state; payment persistence always uses real PostgreSQL."""
    def __init__(self):
        self.hold_id = str(uuid4())
        self.state = 'ACTIVE'
        self.expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.request_id = 'request-1'
        self.fail_lookup = False
        self.lose_confirm = False
        self.lose_cancel = False
        self.confirm_calls = self.cancel_calls = 0
        self.lock = Lock()

    def lookup(self, request_id, hold_id):
        if self.fail_lookup:
            raise requests.Timeout()
        assert str(hold_id) == self.hold_id and request_id == self.request_id
        state = {'ACTIVE':'HELD','CONFIRMED':'CONFIRMED','EXPIRED':'AVAILABLE','CANCELLED':'AVAILABLE'}[self.state]
        return {'success':True,'request_id':request_id,'hold_id':self.hold_id,'hold_status':self.state,
            'hold_expiry':self.expiry if self.state=='ACTIVE' else None,
            'seats':[{'seat_id':'A-1-1','section':'A','row':1,'position_in_row':1,'state':state,
                      'held_by_request_id':request_id if state!='AVAILABLE' else None,
                      'hold_id':self.hold_id if state!='AVAILABLE' else None}]}

    def confirm(self, request_id, hold_id):
        with self.lock:
            self.confirm_calls += 1
            if self.state=='ACTIVE':
                self.state='CONFIRMED'
            if self.lose_confirm:
                raise requests.Timeout()
            return self.lookup(request_id,hold_id)

    def cancel(self, request_id, hold_id):
        with self.lock:
            self.cancel_calls += 1
            if self.state=='ACTIVE':
                self.state='CANCELLED'
            if self.lose_cancel:
                raise requests.Timeout()
            return self.lookup(request_id,hold_id)


@pytest.fixture
def seats():
    return Seats()


def start(lifecycle, seats, outcome='success', key='one'):
    return lifecycle.start_payment(seats.request_id,seats.hold_id,outcome,key)


def test_failed_attempt_history_and_booking_projection(lifecycle,seats):
    first=start(lifecycle,seats,'decline')
    first=lifecycle.reconcile(first['payment_id'])
    assert (first['status'],first['attempt_status'])==('failed','declined')
    original=seats.expiry
    second=start(lifecycle,seats,key='two')
    lifecycle.reconcile(second['payment_id'])
    old=lifecycle.payment(first['payment_id'])
    assert old['status']=='confirmed' and old['attempt_status']=='declined'
    assert seats.expiry==original
    info=lifecycle.checkout(seats.request_id,seats.hold_id)
    assert info['booking_reference']==seats.hold_id and not info['can_pay']
    assert info['original_hold_expiry']==datetime.fromisoformat(original)


@pytest.mark.parametrize('state',['CONFIRMED','EXPIRED','CANCELLED'])
def test_terminal_holds_reject_new_payment(lifecycle,seats,state):
    seats.state=state
    with pytest.raises(Conflict): start(lifecycle,seats)


def test_elapsed_active_deadline_rejects_new_payment(lifecycle,seats):
    seats.expiry=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    with pytest.raises(Conflict): start(lifecycle,seats)


def test_idempotent_replay_during_outage(lifecycle,seats):
    first=start(lifecycle,seats)
    seats.fail_lookup=True
    assert start(lifecycle,seats)['payment_id']==first['payment_id']
    with pytest.raises(Conflict): start(lifecycle,seats,'decline')


def test_duplicate_start_and_database_pending_constraint(lifecycle,seats,db):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _: start(lifecycle,seats),range(12)))
    assert len({r['payment_id'] for r in results})==1
    with pytest.raises(Conflict): start(lifecycle,seats,key='different')
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.connect() as conn:
            conn.execute("INSERT INTO wy_payments(payment_id,hold_id,request_id,attempt_key,outcome,status,attempt_status) "
                         "VALUES (%s,%s,'request-1','bypass','success','pending','pending')",(uuid4(),UUID(seats.hold_id)))


def test_lost_confirm_response_recovered_by_fresh_instance(lifecycle,seats,db):
    p=start(lifecycle,seats)
    seats.lose_confirm=True
    with pytest.raises(requests.Timeout): lifecycle.reconcile(p['payment_id'])
    result=Lifecycle(db,seats).reconcile(p['payment_id'])
    assert result['attempt_status']=='succeeded' and seats.confirm_calls==1


def test_cancel_intent_replay_recovery_and_no_new_payment(lifecycle,seats,db):
    p=start(lifecycle,seats)
    action=lifecycle.start_cancel(seats.request_id,seats.hold_id,'cancel-one')
    assert lifecycle.start_cancel(seats.request_id,seats.hold_id,'cancel-one')['action_id']==action['action_id']
    with pytest.raises(Conflict): start(lifecycle,seats,key='new')
    lifecycle.reconcile(p['payment_id'])
    assert seats.confirm_calls==0
    seats.lose_cancel=True
    with pytest.raises(requests.Timeout): lifecycle.reconcile_cancel(action['action_id'])
    Lifecycle(db,seats).reconcile_cancel(action['action_id'])
    assert lifecycle.cancellation(action['action_id'])['status']=='cancelled'
    assert lifecycle.payment(p['payment_id'])['status']=='cancelled'
    assert seats.cancel_calls==1


def test_confirmation_wins_cancel_race(lifecycle,seats):
    p=start(lifecycle,seats)
    action=lifecycle.start_cancel(seats.request_id,seats.hold_id,'one')
    seats.state='CONFIRMED'
    lifecycle.reconcile_cancel(action['action_id'])
    assert lifecycle.cancellation(action['action_id'])['status']=='confirmed'
    assert lifecycle.payment(p['payment_id'])['status']=='confirmed'
    assert seats.cancel_calls==0


def test_cancel_after_known_terminal_projection(lifecycle,seats):
    seats.state='CONFIRMED'
    lifecycle.checkout(seats.request_id,seats.hold_id)
    action=lifecycle.start_cancel(seats.request_id,seats.hold_id,'one')
    assert action['status']=='confirmed'


def test_unsupported_cancellation_is_visible_and_retryable_by_operator(lifecycle,seats,db):
    action=lifecycle.start_cancel(seats.request_id,seats.hold_id,'one')
    seats.cancel=Mock(side_effect=DependencyError('unsupported',retryable=False))
    lifecycle.recover()
    info=lifecycle.cancellation(action['action_id'])
    assert info['status']=='pending' and info['recovery']['state']=='BLOCKED'
    assert seats.state=='ACTIVE'
    work_id='cancel:'+str(action['action_id'])
    lifecycle.retry_work(work_id)
    assert lifecycle.cancellation(action['action_id'])['recovery']['state']=='READY'


def test_timeout_never_confirms_and_expiry_closes(lifecycle,seats):
    p=start(lifecycle,seats,'timeout')
    lifecycle.recover()
    assert lifecycle.payment(p['payment_id'])['attempt_status']=='pending'
    seats.state='EXPIRED'
    lifecycle.reconcile(p['payment_id'])
    assert lifecycle.payment(p['payment_id'])['attempt_status']=='closed'
    assert seats.confirm_calls==0


def test_events_deduplicate_and_validate_metadata(lifecycle,seats,db):
    event={'event_id':str(uuid4()),'request_id':seats.request_id,'hold_id':seats.hold_id,
           'section':'A','seats':['A-1-1']}
    seats.state='EXPIRED'
    assert lifecycle.receive_expiry(event)=={'success':True}
    lifecycle.receive_expiry(event)
    with pytest.raises(Conflict): lifecycle.receive_expiry(dict(event,section='B'))
    lifecycle.recover()
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM wy_expiry_events').fetchone()['n']==1
        assert conn.execute('SELECT processed_at FROM wy_expiry_events').fetchone()['processed_at']
    assert lifecycle.checkout(seats.request_id,seats.hold_id)['booking_status']=='expired'


def test_poison_event_does_not_starve_valid_later_work(lifecycle,seats,db):
    seats.state='EXPIRED'
    for _ in range(105):
        event={'event_id':str(uuid4()),'request_id':seats.request_id,'hold_id':seats.hold_id,'section':'wrong'}
        lifecycle.receive_expiry(event)
    good={'event_id':str(uuid4()),'request_id':seats.request_id,'hold_id':seats.hold_id}
    lifecycle.receive_expiry(good)
    lifecycle.recover(limit=120)
    with db.connect() as conn:
        assert conn.execute('SELECT processed_at FROM wy_expiry_events WHERE event_id=%s',(UUID(good['event_id']),)).fetchone()['processed_at']
        assert conn.execute("SELECT count(*) AS n FROM wy_work WHERE state='BLOCKED'").fetchone()['n']==105


def test_claim_exclusive_lease_recovery_and_stale_finish(lifecycle,seats,db):
    start(lifecycle,seats)
    with ThreadPoolExecutor(max_workers=3) as pool:
        claims=list(pool.map(lambda _:lifecycle._claim(),range(3)))
    claims=[c for c in claims if c]
    assert len({c['work_id'] for c in claims})==len(claims)==2
    old=claims[0]
    with db.connect() as conn:
        conn.execute("UPDATE wy_work SET lease_until=clock_timestamp()-INTERVAL '1 second' WHERE work_id=%s",(old['work_id'],))
    new=lifecycle._claim()
    assert new['work_id']==old['work_id'] and new['token']!=old['token']
    assert not lifecycle._finish(old,'DONE')
    assert lifecycle._finish(new,'DONE')


def test_notification_durable_and_same_event_retried(lifecycle,seats,db):
    p=start(lifecycle,seats)
    lifecycle.reconcile(p['payment_id'])
    calls=[]
    def sender(url,**kwargs):
        calls.append(kwargs)
        return Mock(status_code=503 if len(calls)==1 else 200)
    lifecycle.status_url='http://consumer/status'
    lifecycle.sender=sender
    lifecycle.recover()
    with db.connect() as conn:
        conn.execute("UPDATE wy_work SET available_at=clock_timestamp() WHERE kind='notification'")
    Lifecycle(db,seats,lifecycle.status_url,sender).recover()
    assert len(calls)==2 and calls[0]['json']==calls[1]['json']
    with db.connect() as conn:
        assert conn.execute('SELECT delivered_at FROM wy_notifications').fetchone()['delivered_at']


def test_upgrade_legacy_schema_backfills_and_preserves_history(db,seats):
    from pathlib import Path
    baseline=Path(__file__).resolve().parents[1]/'schema.sql'
    pid=uuid4()
    with db.connect() as conn:
        conn.execute(baseline.read_text())
        conn.execute("INSERT INTO wy_payments(payment_id,hold_id,attempt_key,request_id,outcome,status) "
                     "VALUES (%s,%s,'one',%s,'decline','confirmed')",(pid,UUID(seats.hold_id),seats.request_id))
    life=Lifecycle(db,seats)
    life.initialize()
    life.initialize()
    row=life.payment(pid)
    assert row['attempt_status']=='declined' and row['status']=='confirmed'
    assert life.ready()=={}


def test_api_legacy_shapes_rich_status_auth_and_errors(lifecycle,seats):
    c=create_app(lifecycle).test_client()
    data={'request_id':seats.request_id,'hold_id':seats.hold_id,'outcome':'decline','attempt_key':'one'}
    r=c.post('/payments',json=data)
    assert r.status_code==200 and set(r.json)=={'payment_id','status'}
    assert c.get('/payments/'+r.json['payment_id']).json=={'status':'pending'}
    assert c.get('/payments/'+r.json['payment_id']+'/details').json['attempt_status']=='pending'
    assert c.get('/checkouts/'+seats.hold_id,query_string={'request_id':seats.request_id}).json['booking_status']=='active'
    assert c.get('/health').status_code==c.get('/ready').status_code==200
    for response in (c.post('/payments',data='{',content_type='application/json'),
                     c.post('/payments',data='x'*20000,content_type='application/json'),
                     c.get('/missing'),c.post('/payments',json=[])):
        assert response.is_json and response.status_code in (400,404,413)
    secure=create_app(lifecycle,api_token='test-only').test_client()
    assert secure.get('/payments/'+r.json['payment_id']).status_code==401
    assert secure.get('/payments/'+r.json['payment_id'],headers={'Authorization':'Bearer test-only'}).status_code==200


def test_bad_dependency_is_not_bad_user_input(lifecycle,seats):
    seats.lookup=Mock(return_value={'hold_status':'ACTIVE'})
    c=create_app(lifecycle).test_client()
    r=c.post('/payments',json={'request_id':seats.request_id,'hold_id':seats.hold_id,'outcome':'success','attempt_key':'one'})
    assert r.status_code==503


def test_http_adapter_accepts_null_confirmed_expiry_and_classifies_bad_shape(seats):
    seats.state='CONFIRMED'
    session=Mock()
    response=Mock(status_code=200)
    session.request.return_value=response
    response.json.return_value=seats.lookup(seats.request_id,seats.hold_id)
    client=SeatClient('http://seat',session=session)
    assert client.lookup(seats.request_id,seats.hold_id)['hold_expiry'] is None
    response.json.return_value={}
    with pytest.raises(DependencyError): client.lookup(seats.request_id,seats.hold_id)
    with pytest.raises(DependencyError): client.cancel(seats.request_id,seats.hold_id)


def test_deferred_wait_does_not_exhaust_network_failure_budget(lifecycle,seats,db):
    p=start(lifecycle,seats,'timeout')
    lifecycle.recover()
    with db.connect() as conn:
        conn.execute("UPDATE wy_work SET attempts=50,available_at=clock_timestamp() WHERE work_id=%s",('payment:'+str(p['payment_id']),))
    seats.fail_lookup=True
    lifecycle.recover()
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM wy_work WHERE work_id=%s',('payment:'+str(p['payment_id']),)).fetchone()
    assert row['state']=='READY' and row['failures']==1 and row['attempts']==51


def test_two_independent_processes_claim_distinct_work(lifecycle,seats,db):
    start(lifecycle,seats)
    script="""
import os
from payment_db import Database
from lifecycle import Lifecycle
try:
    row=Lifecycle(Database(os.environ['PAYMENT_TEST_DSN'],os.environ['PAYMENT_TEST_SCHEMA']),None)._claim()
    print(row['work_id'] if row else 'none')
except Exception as exc:
    print(type(exc).__name__)
    raise SystemExit(1)
"""
    env=dict(os.environ,PAYMENT_TEST_DSN=db.dsn,PAYMENT_TEST_SCHEMA=db.schema)
    def run(_):
        return subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],
                              env=env,capture_output=True,text=True,timeout=20)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,range(2)))
    assert all(r.returncode==0 for r in results)
    assert len({r.stdout.strip() for r in results})==2
    assert all(r.stdout.strip()!='none' for r in results)


def test_live_http_lost_confirm_response_recovers(lifecycle,seats,db):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data=seats.lookup(seats.request_id,seats.hold_id)
            encoded=json.dumps(data).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            length=int(self.headers['Content-Length'])
            json.loads(self.rfile.read(length))
            seats.confirm(seats.request_id,seats.hold_id)
            # Simulate committed effect followed by connection loss, with no HTTP reply.
            self.close_connection=True

        def log_message(self,*args):
            pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        life=Lifecycle(db,SeatClient(f'http://127.0.0.1:{server.server_port}'))
        p=start(life,seats)
        with pytest.raises(DependencyError): life.reconcile(p['payment_id'])
        fresh=Lifecycle(db,SeatClient(f'http://127.0.0.1:{server.server_port}'))
        assert fresh.reconcile(p['payment_id'])['attempt_status']=='succeeded'
        assert seats.confirm_calls==1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_cancel_api_and_cached_checkout_during_outage(lifecycle,seats):
    c=create_app(lifecycle).test_client()
    response=c.post('/checkouts/cancel',json={'request_id':seats.request_id,'hold_id':seats.hold_id,'action_key':'exit'})
    assert response.status_code==202
    seats.fail_lookup=True
    repeat=c.post('/checkouts/cancel',json={'request_id':seats.request_id,'hold_id':seats.hold_id,'action_key':'exit'})
    assert repeat.json['action_id']==response.json['action_id']
    assert c.get('/cancellations/'+response.json['action_id']).json['status']=='pending'
    cached=c.get('/checkouts/'+seats.hold_id,query_string={'request_id':seats.request_id,'cached':'true'})
    assert cached.status_code==200 and cached.json['source']=='cached' and not cached.json['can_pay']
    assert c.get('/checkouts/'+seats.hold_id,query_string={'request_id':seats.request_id}).status_code==503
