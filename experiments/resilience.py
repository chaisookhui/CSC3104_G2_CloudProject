"""Bounded failure experiments, fixed to the private csc3104-lab namespace."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import re
import time
import control
from runtime import LAB, ROOT, api, guard_lab, invariants, k, local, request, sql, utc, write_json


def until(read,predicate,timeout=120):
    deadline=time.monotonic()+timeout
    value=None
    while time.monotonic()<deadline:
        try: value=read()
        except RuntimeError as error:
            value={'transient_error':str(error)}
        try:
            if predicate(value):return value
        except KeyError:pass
        control.sleep(.4)
    raise RuntimeError('Timed out waiting for recovery: '+str(value)[:400])


def fresh(base):
    guard_lab(base)
    state=api(base,'waiting-room/status')
    if state['sale_state']!='pre_sale' or state['waiting_count']:
        raise RuntimeError('This experiment requires a fresh empty pre-sale lab')


def replicas(kind,name):
    return json.loads(k('get',kind,name,'-o','json',capture=True))['spec']['replicas']


def scale(kind,name,count):
    k('scale',kind+'/'+name,'--replicas='+str(count))
    if count:k('rollout','status',kind+'/'+name,'--timeout=180s')
    else:k('wait','--for=delete','pod','-l','app='+name,'--timeout=90s')


@contextmanager
def proxy(mode):
    worker=json.loads(k('get','deployment','allocation-worker','-o','json',capture=True))
    env=worker['spec']['template']['spec']['containers'][0].get('env',[])
    local.apply_object(dict(apiVersion='v1',kind='ConfigMap',metadata=dict(name='experiment-fault-proxy'),
        data={'proxy.py':(ROOT/'experiments/fault_proxy.py').read_text()}),LAB)
    pod=dict(metadata=dict(labels={'app':'experiment-fault-proxy'}),spec=dict(automountServiceAccountToken=False,
        containers=[dict(name='proxy',image='csc3104-frontend:local',imagePullPolicy='Never',
            command=['python','/fault/proxy.py'],env=[dict(name='UPSTREAM',value='http://seat-api:5003'),dict(name='FAULT_MODE',value=mode)],
            ports=[dict(containerPort=5003)],volumeMounts=[dict(name='code',mountPath='/fault',readOnly=True)],
            resources=dict(requests=dict(cpu='25m',memory='32Mi'),limits=dict(cpu='250m',memory='96Mi')))],
        volumes=[dict(name='code',configMap=dict(name='experiment-fault-proxy'))]))
    try:
        local.apply_object(dict(apiVersion='apps/v1',kind='Deployment',metadata=dict(name='experiment-fault-proxy'),
            spec=dict(replicas=1,selector=dict(matchLabels={'app':'experiment-fault-proxy'}),template=pod)),LAB)
        local.apply_object(dict(apiVersion='v1',kind='Service',metadata=dict(name='experiment-fault-proxy'),
            spec=dict(selector={'app':'experiment-fault-proxy'},ports=[dict(port=5003,targetPort=5003)])),LAB)
        k('rollout','status','deployment/experiment-fault-proxy','--timeout=120s')
        k('set','env','deployment/allocation-worker','SEAT_STORE_URL=http://experiment-fault-proxy:5003')
        k('rollout','status','deployment/allocation-worker','--timeout=120s')
        yield
    finally:
        with control.cleanup():
            k('patch','deployment','allocation-worker','--type=json','-p',json.dumps([
                dict(op='replace',path='/spec/template/spec/containers/0/env',value=env)]))
            k('rollout','status','deployment/allocation-worker','--timeout=180s')
            k('delete','deployment,service,configmap','experiment-fault-proxy','--ignore-not-found')


def proxy_control(path):
    return json.loads(k('exec','deployment/experiment-fault-proxy','--','python','-c',
        'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:5003/fault/'+path+'").read().decode() or "null")',capture=True))


def crash_or_lost_reply(base,directory,crash=False):
    fresh(base)
    with proxy('checkpoint' if crash else 'drop'):
        party=api(base,'waiting-room/submit',dict(user_id=directory.name,section='A',party_size=2))
        rid=party['request_id']
        api(base,'waiting-room/sale/start',{})
        events=until(lambda:proxy_control('events'),lambda e:rid in e)
        write_json(directory/'commit-checkpoint.json',dict(at=utc(),events=events))
        if crash:
            before=json.loads(k('get','pods','-l','app=allocation-worker','-o','json',capture=True))
            write_json(directory/'worker-before.json',before)
            pods=[p for p in before['items'] if not p['metadata'].get('deletionTimestamp')]
            if len(pods)!=1:raise RuntimeError('Crash checkpoint requires exactly one allocation worker')
            pod=pods[0]
            if pod['metadata'].get('namespace')!=LAB or pod['spec']['nodeName']!=local.CLUSTER+'-control-plane':
                raise RuntimeError('Refusing to signal a worker outside the private Kind lab')
            cid=pod['status']['containerStatuses'][0]['containerID'].removeprefix('containerd://')
            if not re.fullmatch(r'[a-f0-9]{64}',cid):raise RuntimeError('Unexpected worker container identity')
            # PID 1 is special inside a PID namespace. Signal through its parent
            # container runtime, then require an observed restart before PASS.
            local.run(['docker','exec',pod['spec']['nodeName'],'ctr','--namespace','k8s.io',
                       'tasks','kill','--signal','SIGKILL',cid])
            proxy_control('release')
        current=until(lambda:api(base,'waiting-room/requests/'+rid),lambda p:p['status'] in ('RESERVED','EXPIRED','CANCELLED'),180)
        checkout=api(base,'waiting-room/requests/'+rid+'/checkout')
        checks=invariants()
        holds=json.loads(sql('seats',"SELECT json_agg(row_to_json(h)) FROM (SELECT hold_id,hold_expiry,status FROM holds WHERE request_id='"+rid+"') h;"))
        from workloads import same_deadline
        same=(len(holds)==1 and str(holds[0]['hold_id'])==events[rid]['hold_id'] and checkout.get('hold_id')==events[rid]['hold_id']
              and same_deadline(str(holds[0]['hold_expiry']),events[rid]['hold_expiry'])
              and same_deadline(checkout.get('original_hold_expiry'),events[rid]['hold_expiry']))
        worker_after=json.loads(k('get','pods','-l','app=allocation-worker','-o','json',capture=True))
        restarted=True
        if crash:
            old_ids={p['metadata']['uid'] for p in before['items']}
            new_ids={p['metadata']['uid'] for p in worker_after['items']}
            old_restarts=sum(c.get('restartCount',0) for p in before['items'] for c in p['status'].get('containerStatuses',[]))
            new_restarts=sum(c.get('restartCount',0) for p in worker_after['items'] for c in p['status'].get('containerStatuses',[]))
            restarted=old_ids!=new_ids or new_restarts>old_restarts
        result=dict(status='PASS' if same and restarted and checks['status']=='PASS' else 'FAIL',
            scenario='abrupt-worker-crash-after-seat-commit' if crash else 'lost-seat-hold-response',
            request_id=rid,original=events[rid],recovered=current,checkout=checkout,holds=holds,
            worker_after=worker_after,worker_restart_observed=restarted if crash else None,invariants=checks)
        write_json(directory/'summary.json',result)
        return result


def outage(base,directory,dependency='redis',seconds=30):
    fresh(base)
    if dependency not in ('redis','postgres','both') or not 5<=seconds<=180:raise ValueError('Use redis/postgres/both and 5-180 seconds')
    names=['redis','postgres'] if dependency=='both' else [dependency]
    old={name:replicas('statefulset',name) for name in names}
    keeper=api(base,'waiting-room/submit',dict(user_id=directory.name+'-confirmed',section='B',party_size=1))
    kid=keeper['request_id'];api(base,'waiting-room/sale/start',{})
    keeper=until(lambda:api(base,'waiting-room/requests/'+kid),lambda p:p['status']=='RESERVED')
    khold=keeper['allocation']['hold_id']
    api(base,'payment/payments',dict(request_id=kid,hold_id=khold,outcome='success',attempt_key=directory.name))
    confirmed=until(lambda:api(base,'waiting-room/requests/'+kid+'/checkout'),lambda p:p['booking_status']=='confirmed')
    workers=replicas('deployment','allocation-worker')
    samples=[];rid=None
    # Persist unfinished SQL work BEFORE stopping storage, not only a registration.
    try:
        scale('deployment','allocation-worker',0)
        party=api(base,'waiting-room/submit',dict(user_id=directory.name,section='A',party_size=2))
        rid=party['request_id']
        queued=until(lambda:sql('allocation',"SELECT state FROM allocation_jobs WHERE request_id='"+rid+"';"),lambda s:s=='QUEUED')
        write_json(directory/'durable-before-outage.json',dict(confirmed=confirmed,queued_request_id=rid,job_state=queued))
        for name in names:scale('statefulset',name,0)
        scale('deployment','allocation-worker',workers)
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            samples.append(dict(at=utc(),request=request(base,'waiting-room/requests/'+rid,timeout=6),
                                confirmed_checkout=request(base,'waiting-room/requests/'+kid+'/checkout',timeout=6)))
            control.sleep(min(2,max(0,deadline-time.monotonic())))
    finally:
        with control.cleanup():
            for name,count in old.items():scale('statefulset',name,count)
            scale('deployment','allocation-worker',workers)
            write_json(directory/'outage-samples.json',samples)
    current=until(lambda:api(base,'waiting-room/requests/'+rid),lambda p:p['status'] in ('RESERVED','EXPIRED'),180)
    duplicate=api(base,'waiting-room/submit',dict(user_id=directory.name,section='A',party_size=2))
    checks=invariants()
    retained=until(lambda:api(base,'waiting-room/requests/'+kid+'/checkout'),lambda p:p['booking_status']=='confirmed',180)
    kept=retained['booking_status']=='confirmed' and retained['hold_id']==khold and retained.get('seats')==confirmed.get('seats')
    result=dict(status='PASS' if kept and duplicate['request_id']==rid and checks['status']=='PASS' else 'FAIL',
        dependency=dependency,outage_seconds=seconds,request_id=rid,recovered=current,invariants=checks,
        confirmed_before=confirmed,confirmed_after=retained,queued_job_before_outage=True,
        scope='Confirmed booking, acknowledged registration and unfinished allocation job recovery; not HA or node-loss testing')
    write_json(directory/'summary.json',result);return result


def lifecycle_race(base,directory,near_expiry=False):
    fresh(base)
    party=api(base,'waiting-room/submit',dict(user_id=directory.name,section='A',party_size=2))
    rid=party['request_id'];api(base,'waiting-room/sale/start',{})
    party=until(lambda:api(base,'waiting-room/requests/'+rid),lambda p:p['status']=='RESERVED')
    hold=party['allocation']['hold_id']
    if near_expiry:
        from datetime import datetime, timezone
        expiry=datetime.fromisoformat(party['allocation']['hold_expiry'].replace('Z','+00:00'))
        while (expiry-datetime.now(timezone.utc)).total_seconds()>.15:control.sleep(.1)
    import threading
    gate=threading.Barrier(3)
    def send(path,body):
        gate.wait();return request(base,path,body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pay=pool.submit(send,'payment/payments',dict(request_id=rid,hold_id=hold,outcome='success',attempt_key=directory.name))
        cancel=pool.submit(send,'payment/checkouts/cancel',dict(request_id=rid,hold_id=hold,action_key=directory.name))
        gate.wait();responses=[pay.result(),cancel.result()]
    checkout=until(lambda:api(base,'waiting-room/requests/'+rid+'/checkout'),
        lambda p:p['booking_status'] in ('confirmed','cancelled','expired') and not p.get('payment_pending'),120)
    # Observe again after asynchronous work drains, then assert DB ownership.
    monitor=until(lambda:json.loads(k('exec','deployment/payment-api','--','python','service.py','monitor',capture=True)),
                  lambda m:m['pending']['count']==0 and not any(w['kind']!='notification' for w in m['work']),120)
    checkout=api(base,'waiting-room/requests/'+rid+'/checkout');checks=invariants()
    valid=all(r['status'] in (200,202,409) for r in responses) and checkout['booking_status'] in ('confirmed','cancelled','expired')
    result=dict(status='PASS' if valid and checks['status']=='PASS' else 'FAIL',near_expiry=near_expiry,
        request_id=rid,hold_id=hold,responses=responses,checkout=checkout,payment_monitor=monitor,invariants=checks,
        interpretation='Any consistent terminal winner is valid; scheduling does not guarantee which operation wins. '
            'Payment/cancellation/projection work must drain; optional notification outbox items can await an unconfigured callback URL.')
    write_json(directory/'summary.json',result);return result
