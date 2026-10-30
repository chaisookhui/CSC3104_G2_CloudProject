"""Payment-owned admission, observability and capability-security acceptance tests."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from werkzeug.exceptions import Unauthorized

from lifecycle import Lifecycle, Conflict, DependencyError
from payment_monitoring import snapshot
from payment_retry import retry_delay
from payment_security import CheckoutTokens
from service import create_app
from test_payment import Seats

KEY='test-only-checkout-signing-key-32-characters'
INTERNAL='test-only-internal-service-credential'


@pytest.fixture
def seats():
    return Seats()


def grant(seats,scopes=('read','pay','cancel')):
    return CheckoutTokens(KEY).issue('alice',seats.request_id,seats.hold_id,scopes=scopes)


def secure_client(lifecycle):
    return create_app(lifecycle,api_token=INTERNAL,checkout_key=KEY).test_client()


def test_customer_routes_are_optional_and_credentials_are_separate(lifecycle,seats):
    assert create_app(lifecycle).test_client().get('/customer/checkout').status_code==404
    c=secure_client(lifecycle)
    assert c.get('/customer/checkout').status_code==401
    assert c.get('/customer/checkout',headers={'Authorization':'Bearer '+INTERNAL}).status_code==401
    assert c.get('/metrics',headers={'Authorization':'Bearer '+grant(seats)}).status_code==401
    assert c.get('/customer/checkout',headers={'Authorization':'Bearer '+grant(seats)}).status_code==200


def test_invalid_expired_wrong_audience_and_tampered_tokens(seats):
    tokens=CheckoutTokens(KEY)
    token=grant(seats)
    data=tokens.serializer.loads(token)
    for changed in (dict(data,exp=0),dict(data,aud='another-service'),dict(data,iat=True),
                    dict(data,scopes=['admin']),dict(data,hold_id='invalid')):
        with pytest.raises(Unauthorized):
            tokens.verify(tokens.serializer.dumps(changed),'read')
    with pytest.raises(Unauthorized):
        tokens.verify(token[:2]+('A' if token[2]!='A' else 'B')+token[3:],'read')
    with pytest.raises(ValueError):
        tokens.issue('alice',seats.request_id,seats.hold_id,ttl=901)


def test_customer_cannot_change_identity_outcome_or_amount(lifecycle,seats):
    c=secure_client(lifecycle)
    headers={'Authorization':'Bearer '+grant(seats)}
    for field,value in (('hold_id',str(uuid4())),('request_id','bob'),('outcome','success'),('amount',1),('card_number','123')):
        assert c.post('/customer/payments',json={'attempt_key':'one',field:value},headers=headers).status_code==400
    reply=c.post('/customer/payments',json={'attempt_key':'one'},headers=headers)
    assert reply.status_code==200
    assert c.post('/customer/payments',json={'attempt_key':'one'},headers=headers).json==reply.json
    lifecycle.recover()
    assert c.get('/customer/payments/'+reply.json['payment_id'],headers=headers).json['status']=='confirmed'


def test_read_only_scope_and_foreign_payment_are_denied(lifecycle,seats):
    c=secure_client(lifecycle)
    own={'Authorization':'Bearer '+grant(seats)}
    payment=c.post('/customer/payments',json={'attempt_key':'one'},headers=own).json
    read_only={'Authorization':'Bearer '+grant(seats,('read',))}
    assert c.post('/customer/payments',json={'attempt_key':'two'},headers=read_only).status_code==403
    assert c.post('/customer/cancel',json={'action_key':'exit'},headers=read_only).status_code==403
    foreign=CheckoutTokens(KEY).issue('bob','request-bob',uuid4())
    assert c.get('/customer/payments/'+payment['payment_id'],headers={'Authorization':'Bearer '+foreign}).status_code==404
    cancel=c.post('/customer/cancel',json={'action_key':'exit'},headers=own)
    assert cancel.status_code==202
    assert c.get('/customer/cancellations/'+cancel.json['action_id'],headers={'Authorization':'Bearer '+foreign}).status_code==404


def test_customer_outcome_is_configured_server_side(lifecycle,seats):
    c=create_app(lifecycle,api_token=INTERNAL,checkout_key=KEY,customer_outcome='decline').test_client()
    headers={'Authorization':'Bearer '+grant(seats)}
    reply=c.post('/customer/payments',json={'attempt_key':'one'},headers=headers)
    lifecycle.recover()
    assert c.get('/customer/payments/'+reply.json['payment_id'],headers=headers).json['attempt_status']=='declined'


def test_backlog_bound_is_atomic_across_concurrent_admissions(lifecycle,db):
    parties=[Seats(),Seats()]
    def attempt(seats):
        try:
            return Lifecycle(db,seats,max_pending=1).start_payment(seats.request_id,seats.hold_id,'success','one')
        except DependencyError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,parties))
    assert sum(r is not None for r in results)==1
    winner=next(i for i,r in enumerate(results) if r is not None)
    seats=parties[winner]
    life=Lifecycle(db,seats,max_pending=1)
    assert life.start_payment(seats.request_id,seats.hold_id,'success','one')['payment_id']==results[winner]['payment_id']
    # Cancellation is still admitted while payment backlog is full.
    assert life.start_cancel(seats.request_id,seats.hold_id,'exit')['status']=='pending'


def test_per_hold_attempt_bound_does_not_extend_deadline(lifecycle,seats,db):
    life=Lifecycle(db,seats,max_attempts_per_hold=2)
    for key in ('one','two'):
        row=life.start_payment(seats.request_id,seats.hold_id,'decline',key)
        life.reconcile(row['payment_id'])
    with pytest.raises(Conflict,match='attempt limit'):
        life.start_payment(seats.request_id,seats.hold_id,'decline','three')
    assert life.start_payment(seats.request_id,seats.hold_id,'decline','one')['attempt_status']=='declined'
    assert life.checkout(seats.request_id,seats.hold_id)['original_hold_expiry'].isoformat()==seats.expiry
    assert not life.checkout(seats.request_id,seats.hold_id)['can_pay']


def test_audit_is_atomic_deduplicated_and_contains_no_credentials(lifecycle,seats,db):
    c=secure_client(lifecycle)
    headers={'Authorization':'Bearer '+grant(seats)}
    for _ in range(2):
        assert c.post('/customer/payments',json={'attempt_key':'private-key-not-for-audit'},headers=headers).status_code==200
    lifecycle.recover()
    with db.connect() as conn:
        rows=conn.execute('SELECT action,actor,details FROM wy_audit').fetchall()
    assert sum(r['action']=='payment.accepted' for r in rows)==1
    assert next(r['actor'] for r in rows if r['action']=='payment.accepted')=='alice'
    text=json.dumps(rows,default=str)
    assert KEY not in text and INTERNAL not in text and 'private-key-not-for-audit' not in text


def test_audit_failure_rolls_back_accepted_payment(lifecycle,seats,db,monkeypatch):
    import lifecycle as implementation
    def fail(*args,**kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(implementation,'audit',fail)
    with pytest.raises(RuntimeError):
        lifecycle.start_payment(seats.request_id,seats.hold_id,'success','one')
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM wy_payments').fetchone()['n']==0
        assert conn.execute('SELECT count(*) AS n FROM wy_work').fetchone()['n']==0


def test_metrics_cover_latency_backlog_failures_and_worker_heartbeat(lifecycle,seats,db):
    c=secure_client(lifecycle)
    auth={'Authorization':'Bearer '+INTERNAL}
    assert c.get('/metrics').status_code==401
    assert snapshot(db)['worker_heartbeat_age_seconds'] is None
    assert c.post('/payments',json={'request_id':seats.request_id,'hold_id':seats.hold_id,
                                 'outcome':'timeout','attempt_key':'one'},headers=auth).status_code==200
    lifecycle.recover()
    with db.connect() as conn:
        conn.execute("UPDATE wy_work SET state='BLOCKED',failures=3 WHERE kind='payment'")
    reply=c.get('/metrics',headers=auth)
    assert reply.status_code==200
    for metric in ('payment_http_requests_total','payment_http_duration_seconds_sum','payment_pending_attempts 1',
                   'state="BLOCKED"','payment_work_failures','payment_worker_heartbeat_present 1'):
        assert metric in reply.text
    assert seats.hold_id not in reply.text and seats.request_id not in reply.text
    assert KEY not in reply.text and INTERNAL not in reply.text


def test_retry_jitter_is_bounded_and_nonzero():
    for failures,ceiling in ((1,2),(3,8),(30,300)):
        assert retry_delay(failures,uniform=lambda low,high:low)==ceiling/2
        assert retry_delay(failures,uniform=lambda low,high:high)==ceiling


def test_expiry_while_queued_never_confirms_or_extends_hold(lifecycle,seats):
    payment=lifecycle.start_payment(seats.request_id,seats.hold_id,'success','one')
    seats.state='EXPIRED'
    lifecycle.recover()
    assert lifecycle.payment(payment['payment_id'])['status']=='expired'
    assert seats.confirm_calls==0


def test_unknown_event_fields_are_not_persisted(lifecycle,seats,db):
    with pytest.raises(ValueError,match='Unexpected'):
        lifecycle.receive_expiry({'event_id':str(uuid4()),'hold_id':seats.hold_id,
                                 'request_id':seats.request_id,'card_number':'not-accepted'})
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM wy_expiry_events').fetchone()['n']==0


def test_conflicting_late_event_cannot_downgrade_confirmed_booking(lifecycle,seats,db):
    payment=lifecycle.start_payment(seats.request_id,seats.hold_id,'success','one')
    lifecycle.reconcile(payment['payment_id'])
    lifecycle.receive_expiry({'event_id':str(uuid4()),'hold_id':seats.hold_id,'request_id':seats.request_id})
    lifecycle.recover()
    assert lifecycle.payment(payment['payment_id'])['status']=='confirmed'
    with db.connect() as conn:
        assert conn.execute("SELECT state FROM wy_work WHERE kind='event'").fetchone()['state']=='BLOCKED'
        assert conn.execute("SELECT count(*) AS n FROM wy_audit WHERE action='work.blocked'").fetchone()['n']==1


def test_payment_acceptance_survives_abrupt_process_exit(lifecycle,seats,db):
    script="""
import os,json
from payment_db import Database
from lifecycle import Lifecycle
class Remote:
    def lookup(self,*args): return json.loads(os.environ['PAYMENT_TEST_HOLD'])
try:
    db=Database(os.environ['PAYMENT_TEST_DSN'],os.environ['PAYMENT_TEST_SCHEMA'])
    data=json.loads(os.environ['PAYMENT_TEST_HOLD'])
    Lifecycle(db,Remote()).start_payment(data['request_id'],data['hold_id'],'success','crash')
    os._exit(0)
except Exception as exc:
    print(type(exc).__name__,flush=True)
    os._exit(1)
"""
    env=dict(os.environ,PAYMENT_TEST_DSN=db.dsn,PAYMENT_TEST_SCHEMA=db.schema,
             PAYMENT_TEST_HOLD=json.dumps(seats.lookup(seats.request_id,seats.hold_id)))
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],
                          env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout
    Lifecycle(db,seats).recover()
    with db.connect() as conn:
        assert conn.execute('SELECT status FROM wy_payments').fetchone()['status']=='confirmed'
    assert seats.confirm_calls==1
