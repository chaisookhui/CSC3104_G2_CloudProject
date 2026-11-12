"""Small final acceptance: paired policy, booking flow, worker/dependency recovery.

Uses only an initially absent csc3104-check namespace; main/lab are preserved.
--pair-only is the bounded CI policy integration check.
"""
import argparse
import json
import sys
import time
from uuid import uuid4

import runtime
import run
import workloads


def wait(read, check, timeout=90):
    deadline=time.monotonic()+timeout
    last=None
    while time.monotonic()<deadline:
        try:
            last=read()
            if check(last): return last
        except RuntimeError as error:
            last={'temporarily_unavailable':str(error)}
        time.sleep(.5)
    raise RuntimeError('Timed out waiting for '+str(last)[:300])


def scale(name,count):
    runtime.k('scale','deployment/'+name,f'--replicas={count}')
    if count:
        runtime.k('rollout','status','deployment/'+name,'--timeout=180s')
    else:
        runtime.k('wait','--for=delete','pod','-l','app='+name,'--timeout=90s')


def faults(base,directory):
    request=lambda path,body=None: runtime.api(base,path,body)
    def reserve(label):
        p=request('waiting-room/submit',dict(user_id='fault-'+label+'-'+uuid4().hex[:8],section='A',party_size=1))
        return p['request_id']
    def party(rid): return request('waiting-room/requests/'+rid)
    def checkout(rid): return request('waiting-room/requests/'+rid+'/checkout')
    def pay(rid,p): return request('payment/payments',dict(request_id=rid,hold_id=p['allocation']['hold_id'],outcome='success',attempt_key='fault-pay:'+rid))
    result={}
    try:
        scale('allocation-worker',0)
        rid=reserve('W2');request('waiting-room/sale/start',{})
        wait(lambda: runtime.sql('allocation',"SELECT count(*) FROM allocation_jobs WHERE state='QUEUED';"),lambda n:int(n)>0)
        runtime.write_json(directory/'W2-paused.json',runtime.capture(base,'W2','paused'))
        scale('allocation-worker',1)
        p=wait(lambda:party(rid),lambda p:p['status']=='RESERVED')
        result['W2']={'status':'PASS','request_id':rid,'hold_id':p['allocation']['hold_id']}

        scale('payment-worker',0)
        payment=pay(rid,p)
        observed=runtime.capture(base,'W1','paused')
        assert observed['observations']['payment_health']['status']==200
        assert observed['payment_monitor']['pending']['count']>=1
        runtime.write_json(directory/'W1-paused.json',observed)
        scale('payment-worker',1)
        final=wait(lambda:checkout(rid),lambda c:c['booking_status']=='confirmed')
        assert final['hold_id']==p['allocation']['hold_id']
        assert workloads.same_deadline(final['original_hold_expiry'],p['allocation']['hold_expiry'])
        result['W1']={'status':'PASS','payment_id':payment['payment_id'],'request_id':rid}

        scale('payment-worker',0)
        rid2=reserve('R3');p2=wait(lambda:party(rid2),lambda p:p['status']=='RESERVED')
        payment2=pay(rid2,p2)
        scale('seat-api',0);scale('payment-worker',1)
        time.sleep(2)
        outage=runtime.capture(base,'R3','seat-api-outage')
        assert outage['payment_monitor']['pending']['count']>=1
        runtime.write_json(directory/'R3-outage.json',outage)
        scale('seat-api',1)
        final2=wait(lambda:checkout(rid2),lambda c:c['booking_status']=='confirmed')
        assert final2['hold_id']==p2['allocation']['hold_id']
        assert workloads.same_deadline(final2['original_hold_expiry'],p2['allocation']['hold_expiry'])
        result['R3']={'status':'PASS','request_id':rid2,'payment_id':payment2['payment_id']}
        wait(lambda:runtime.sql('payment',"SELECT count(*) FROM wy_payments WHERE attempt_status='pending';"),lambda n:int(n)==0)

        def saved():
            return dict(holds=json.loads(runtime.sql('seats',"SELECT json_agg(row_to_json(s)) FROM (SELECT hold_id,request_id,status FROM holds ORDER BY request_id) s;")),
                        payments=json.loads(runtime.sql('payment',"SELECT json_agg(row_to_json(s)) FROM (SELECT payment_id,attempt_status,status FROM wy_payments ORDER BY payment_id) s;")),
                        pvc={p['metadata']['name']:p['metadata']['uid'] for p in json.loads(runtime.k('get','pvc','-o','json',capture=True))['items']},
                        queue=sorted((p['request_id'],p['queue_number']) for p in request('waiting-room/queue')['requests']))
        before=saved();runtime.write_json(directory/'R2-before.json',before)
        runtime.k('delete','pod','postgres-0','redis-0','--wait=true')
        for name in ('postgres','redis'): runtime.k('rollout','status','statefulset/'+name,'--timeout=180s')
        after=wait(saved,lambda value:value==before)
        runtime.write_json(directory/'R2-after.json',after)
        result['R2']={'status':'PASS','same_pvc_uids':True,'same_holds_payments_queue':True}
        rid3=reserve('R2-after');p3=wait(lambda:party(rid3),lambda p:p['status']=='RESERVED')
        pay(rid3,p3);wait(lambda:checkout(rid3),lambda c:c['booking_status']=='confirmed')
        result['R2']['new_booking_confirmed']=True
        checks=runtime.invariants();assert checks['status']=='PASS',checks
        runtime.write_json(directory/'invariants.json',checks)
        runtime.write_json(directory/'after.json',runtime.capture(base,'faults','after'))
        runtime.write_json(directory/'summary.json',dict(status='PASS',namespace=runtime.LAB,cases=result,invariants=checks))
        return result
    finally:
        # All target mutations are within this disposable namespace.
        for name in ('allocation-worker','payment-worker','seat-api'): scale(name,1)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pair-only',action='store_true');args=parser.parse_args()
    target=runtime.local.TEST_NAMESPACE
    if runtime.local.kubectl('get','namespace',target,'--ignore-not-found','-o','name',namespace=None,capture=True):
        raise RuntimeError('Existing csc3104-check found; do not run concurrent verification/deployment')
    runtime.LAB=target;run.LAB=target
    name=time.strftime('acceptance-%Y%m%d-%H%M%S')
    directory=runtime.run_directory(name)
    summary={'namespace':target,'scope':'Bounded integration acceptance, not statistical fairness or load capacity','cases':{}}
    try:
        trace=runtime.ROOT/'.local/traces'/f'{name}.json';trace.parent.mkdir(parents=True,exist_ok=True)
        runtime.write_json(trace,workloads.make_trace('F1',8,41,10))
        sys.argv=['run.py','compare','--trace',str(trace),'--reset-lab','--hold-ttl','30','--run',name+'-pair']
        assert run.main()==0,'Final paired comparison did not pass'
        summary['cases']['F01']='PASS'
        if not args.pair_only:
            runtime.setup_lab(True,hold_ttl=30,batch_size=10)
            with runtime.lab_connection() as base:
                sys.path.insert(0,str(runtime.ROOT/'tests'))
                from docker_booking_smoke import BookingCheck
                BookingCheck(base,90).run()
                summary['cases']['B1-B5/Q01']='PASS - real-network booking checker'
                runtime.write_json(directory/'booking-after.json',runtime.capture(base,'booking','after'))
            runtime.setup_lab(True,hold_ttl=120,batch_size=10)
            with runtime.lab_connection() as base:
                summary['cases'].update(faults(base,directory))
        summary['status']='PASS';runtime.write_json(directory/'summary.json',summary)
        print('PASS: final bounded acceptance',directory,flush=True)
    except BaseException as error:
        summary.update(status='FAIL',error=type(error).__name__,message=str(error))
        runtime.write_json(directory/'summary.json',summary);raise
    finally:
        runtime.local.kubectl('delete','namespace',target,'--ignore-not-found','--wait=true','--timeout=180s',namespace=None)
        (runtime.local.LOCAL/f'secrets-{target}.json').unlink(missing_ok=True)


if __name__=='__main__':
    try: main()
    except (RuntimeError,ValueError,OSError,AssertionError) as error:
        print('Acceptance stopped: '+str(error),file=sys.stderr);sys.exit(1)
