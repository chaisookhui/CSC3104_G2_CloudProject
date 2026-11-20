"""Complete final-version coverage gaps before merging the submission reports.

Reuses runtime, workloads and original invariants. Resets only csc3104-lab;
TC09 uses a separate Compose project. Existing final v9 studies are audited,
not replaced by smaller workloads. Requires explicit --reset-lab.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import runtime as rt
from acceptance import scale, wait
from workloads import contention, same_deadline

ROOT = rt.ROOT
BUNDLE = Path('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1112-737-0_26.1112.737.0_x64__3k8sg7r9htsxt/dependencies')
BUNDLED_NODE = BUNDLE/'node/bin/node.exe'
NODE = Path(os.environ.get('EXAM_NODE') or (str(BUNDLED_NODE) if BUNDLED_NODE.is_file() else shutil.which('node') or 'node'))


def save(path, value):
    rt.write_json(path, value)
    return value


def browser(base, mode, folder, profile, data=None):
    folder.mkdir(parents=True, exist_ok=True)
    command = [str(NODE), str(ROOT/'experiments/examiner_browser.cjs'), base, mode, str(folder), str(profile)]
    if data is not None:
        save(folder/'input.json', data)
        command.append(str(folder/'input.json'))
    env = dict(os.environ, EXAM_PLAYWRIGHT=os.environ.get('EXAM_PLAYWRIGHT',str(BUNDLE/'node/node_modules/playwright')))
    with (folder/'browser-console.log').open('w', encoding='utf-8') as log:
        code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=650).returncode
    if not (folder/'browser-result.json').exists():
        raise RuntimeError(f'Browser bootstrap exited {code}; see {folder / "browser-console.log"}')
    result = json.loads((folder/'browser-result.json').read_text())
    assert code == 0 and result['status'] == 'PASS', (mode, result.get('error'), folder)
    return result


def fresh(folder):
    rt.setup_lab(True, hold_ttl=300, batch_size=10)
    folder.mkdir(parents=True, exist_ok=True)


def invariant(folder):
    checks = save(folder/'invariants.json', rt.invariants())
    assert checks['status'] == 'PASS' and checks['violations'] == 0, checks
    return checks


def stable(a, b):
    assert a['request_id'] == b['request_id'] and a['hold_id'] == b['hold_id']
    assert same_deadline(a['original_hold_expiry'], b['original_hold_expiry'])
    assert [s['seat_id'] for s in a['seats']] == [s['seat_id'] for s in b['seats']]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reset-lab', action='store_true', required=True)
    p.add_argument('--run', required=True)
    p.add_argument('--only', choices=['journeys', 'capacity', 'validation', 'flow', 'contention', 'compose', 'replacement', 'payment-pause', 'allocation-pause', 'seat-outage', 'storage', 'browser'])
    args = p.parse_args()
    directory = rt.run_directory(args.run)
    if any(directory.iterdir()):
        raise RuntimeError('Choose a new run ID; preserve previous results')
    summary = dict(started_at=rt.utc(), status='RUNNING', results={}, run=args.run)
    save(directory/'run.json', dict(arguments=vars(args), started_at=rt.utc()))
    for source in (ROOT/'experiments/examiner_verify.py',ROOT/'experiments/examiner_browser.cjs'):
        shutil.copy2(source,directory/('harness-'+source.name))
    profiles = ROOT/'.local/examiner-browser-profiles'/args.run
    profiles.mkdir(parents=True, exist_ok=True)
    inventory = json.loads((ROOT/'output/validation/tc-fixes/runtime-inventory.json').read_text())
    app_hashes = {name: digest for name, digest in inventory['source_sha256'].items()
                  if name.startswith(('src/', 'frontend/', 'infra/')) or name == 'demo.py'}
    mismatches = [name for name, digest in app_hashes.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest]
    save(directory/'application-continuity.json', dict(status='FAIL' if mismatches else 'PASS', checked=app_hashes, mismatches=mismatches))
    assert not mismatches, 'Application changed after v9: '+str(mismatches)
    main_before = json.loads(rt.local.kubectl('get', 'deployments', '-o', 'json', namespace='csc3104', capture=True))
    save(directory/'main-before.json', {d['metadata']['name']:dict(uid=d['metadata']['uid'], spec=d['spec']) for d in main_before['items']})

    def record(ids, work):
        if args.only and args.only != work.__name__:
            return
        folder = directory/work.__name__
        folder.mkdir()
        print('START', ids, work.__name__, flush=True)
        try:
            values = work(folder)
            summary['results'].update({case:dict(status='PASS', evidence=str(folder.relative_to(ROOT)).replace('\\','/'), details=values) for case in ids})
            print('PASS', ids, flush=True)
        except Exception as error:
            failure = dict(status='FAIL', error=type(error).__name__, message=str(error), traceback=traceback.format_exc(), at=rt.utc())
            save(folder/'failure.json', failure)
            summary['results'].update({case:dict(status='FAIL', evidence=str(folder.relative_to(ROOT)), error=failure) for case in ids})
            print('FAIL', ids, repr(error), flush=True)
        save(directory/'summary.json', summary)

    def journeys(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            save(folder/'before.json', rt.capture(base, 'TC01-04', 'before'))
            result = browser(base, 'journeys', folder/'browser', profiles/'journeys')
            invariant(folder)
            save(folder/'after.json', rt.capture(base, 'TC01-04', 'after'))
            return dict(browser_checks=result['checks'], cases=result['cases'])

    def capacity(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            result = browser(base, 'capacity', folder/'browser', profiles/'capacity')
            checks = invariant(folder)
            assert checks['counts']['held'] == 8 and checks['counts']['confirmed'] == 0
            save(folder/'after.json', rt.capture(base, 'TC05', 'after'))
            return result

    def validation(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            before = rt.api(base, 'waiting-room/queue')
            invalid = [dict(user_id='bad-size0', section='A', party_size=0), dict(user_id='bad-size5', section='A', party_size=5),
                       dict(user_id='bad-bool', section='A', party_size=True), dict(user_id='bad-section', section='Z', party_size=1),
                       dict(user_id='', section='A', party_size=1), dict(section='A')]
            responses = [rt.request(base, 'waiting-room/submit', body) for body in invalid]
            responses += [rt.request(base, 'waiting-room/requests/nonexistent-final'), rt.request(base, 'seats/seats/Z')]
            after = rt.api(base, 'waiting-room/queue')
            save(folder/'responses.json', responses)
            save(folder/'queue-before.json', before); save(folder/'queue-after.json', after)
            assert [r['status'] for r in responses] == [400]*6+[404]*2
            assert before == after
            return dict(assertions=8, statuses=[r['status'] for r in responses], queue_unchanged=True)

    def flow(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            save(folder/'before.json', rt.capture(base, 'TC07', 'before'))
            result = browser(base, 'service-flow', folder/'browser', profiles/'flow')
            queue = wait(lambda:rt.api(base,'waiting-room/queue'), lambda q:q['count']==5 and len([r for r in q['requests'] if r['status']=='RESERVED'])==5)
            late = [r for r in queue['requests'] if r['user_id'].startswith('sim-')]
            assert len(late)==4 and all(r['entry_type']=='latecomer' and r['party_size']==1 and r['section']=='B' for r in late)
            dispatcher = wait(lambda:rt.api(base,'dispatcher/status'), lambda s:s.get('current') is None)
            callbacks = wait(lambda:int(rt.sql('allocation',"SELECT count(*) FROM allocation_completions WHERE delivered=0;")),lambda n:n==0)
            save(folder/'queue.json',queue);save(folder/'dispatcher.json',dispatcher)
            (folder/'worker.log').write_text(rt.k('logs','deployment/allocation-worker','--tail=250',capture=True),encoding='utf-8')
            invariant(folder);save(folder/'after.json',rt.capture(base,'TC07','after'))
            return dict(original=result['original'], late_requests=late, callbacks_remaining=callbacks, dispatcher=dispatcher)

    def contention_case(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            save(folder/'before.json',rt.capture(base,'TC08','before'))
            result=contention(base,folder,20,20,False)
            assert result['status']=='PASS',result
            counts=result.get('outcomes',{})
            assert counts.get('RESERVED')==10 and counts.get('UNAVAILABLE')==10,counts
            invariant(folder);save(folder/'after.json',rt.capture(base,'TC08','after'))
            return result
    contention_case.__name__='contention'

    def compose(folder):
        project='csc3104-exam-'+args.run[-12:].lower()
        env=dict(os.environ,COMPOSE_PROJECT_NAME=project)
        port=18280
        command=[sys.executable,'demo.py','--port',str(port)]
        def run(command,name,**kwargs):
            with (folder/name).open('w',encoding='utf-8') as log:
                r=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600,**kwargs)
            assert r.returncode==0,(name,r.returncode)
        prefix=['docker','compose','--env-file','.env.core','-f','compose.core.yaml','-p',project]
        try:
            run(command,'startup.log')
            raw=subprocess.check_output(prefix+['ps','-a','--format','json'],cwd=ROOT,env=env,text=True)
            rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
            save(folder/'containers.json',rows)
            runtime_rows=[r for r in rows if r['Service'] not in ('seat-init','allocation-init','payment-migrate')]
            init_rows=[r for r in rows if r['Service'] in ('seat-init','allocation-init','payment-migrate')]
            assert len(runtime_rows)==13 and all(r['State']=='running' for r in runtime_rows),[(r['Service'],r['State']) for r in rows]
            assert len(init_rows)==3 and all(r['ExitCode']==0 for r in init_rows)
            assert all(not any(p.get('PublishedPort',0) for p in r.get('Publishers',[])) for r in rows if r['Service']!='frontend')
            frontend=next(r for r in rows if r['Service']=='frontend')
            published=[p for p in frontend['Publishers'] if p.get('PublishedPort',0)]
            assert published and all(p['URL']=='127.0.0.1' and p['PublishedPort']==port for p in published)
            health=rt.request('http://127.0.0.1:'+str(port),'seats/health')
            save(folder/'health.json',health);assert health['status']==200 and health['data']['storage']=='postgresql',health
            run(prefix+['logs','--tail','40'],'compose.log')
            return dict(project=project,running=len(runtime_rows),init_exit_zero=len(init_rows),health=health,only_frontend_loopback=True)
        finally:
            run(prefix+['down'],'cleanup.log')

    def replacement(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            original=browser(base,'book',folder/'before-browser',profiles/'replacement')['booking']
            before=json.loads(rt.k('get','pods','-l','app=allocation-api','-o','json',capture=True))
            pvc=json.loads(rt.k('get','pvc','-o','json',capture=True))
            save(folder/'pods-before.json',before);save(folder/'pvc-before.json',pvc)
            save(folder/'endpoints-before.json',json.loads(rt.k('get','endpointslices','-o','json',capture=True)))
            deployment=json.loads(rt.k('get','deployment','allocation-api','-o','json',capture=True));save(folder/'deployment-probes.json',deployment)
            container=deployment['spec']['template']['spec']['containers'][0]
            assert all(k in container for k in ('startupProbe','readinessProbe','livenessProbe'))
            rt.k('delete','pods','-l','app=allocation-api','--wait=true');rt.k('rollout','status','deployment/allocation-api','--timeout=180s')
            after=json.loads(rt.k('get','pods','-l','app=allocation-api','-o','json',capture=True));save(folder/'pods-after.json',after)
            assert {p['metadata']['uid'] for p in before['items']}.isdisjoint(p['metadata']['uid'] for p in after['items'])
            endpoints=json.loads(rt.k('get','endpointslices','-o','json',capture=True));save(folder/'endpoints-after.json',endpoints)
            new_uid=after['items'][0]['metadata']['uid']
            assert any(e.get('targetRef',{}).get('uid')==new_uid and e.get('conditions',{}).get('ready') for s in endpoints['items'] for e in s.get('endpoints',[]))
            restored=browser(base,'inspect',folder/'after-browser',profiles/'replacement',dict(user=original['user'],status='confirmed',original=original))
            stable(original['checkout'],restored['booking']['checkout'])
            assert {p['metadata']['uid'] for p in pvc['items']}=={p['metadata']['uid'] for p in json.loads(rt.k('get','pvc','-o','json',capture=True))['items']}
            invariant(folder)
            return dict(original=original,restored=restored['booking'],new_pod_uid=new_uid,service_endpoint_ready=True)

    def monitor():
        return json.loads(rt.k('exec','deployment/payment-api','--','python','service.py','monitor',capture=True))

    def payment_pause(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            original=browser(base,'reserve',folder/'reserve',profiles/'payment-pause')['booking']
            try:
                scale('payment-worker',0)
                browser(base,'pay-pending',folder/'pending-browser',profiles/'payment-pause',dict(user=original['user']))
                paused=save(folder/'paused.json',rt.capture(base,'TC11','paused'))
                assert paused['payment_monitor']['pending']['count']==1
                assert paused['invariants']['counts']['confirmed']==0
                pending=save(folder/'checkout-paused.json',rt.api(base,'waiting-room/requests/'+original['request']['request_id']+'/checkout'))
                assert pending['booking_status']=='active';stable(original['checkout'],pending)
                scale('payment-worker',1)
                final=wait(lambda:rt.api(base,'waiting-room/requests/'+original['request']['request_id']+'/checkout'),lambda c:c['booking_status']=='confirmed')
                stable(original['checkout'],final);assert len(final['payment_attempts'])==1
                browser(base,'inspect',folder/'final-browser',profiles/'payment-pause',dict(user=original['user'],status='confirmed',original=original))
                invariant(folder);save(folder/'final.json',final)
                return dict(original=original,paused=pending,confirmed=final)
            finally:scale('payment-worker',1)
    payment_pause.__name__='payment-pause'

    def allocation_pause(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            try:
                scale('allocation-worker',0)
                original=browser(base,'register-pre',folder/'register',profiles/'allocation-pause',dict(section='B',size=2))['booking']
                rt.api(base,'waiting-room/sale/start',{})
                wait(lambda:int(rt.sql('allocation',"SELECT count(*) FROM allocation_jobs WHERE state='QUEUED';")),lambda n:n==1)
                paused=save(folder/'paused.json',rt.capture(base,'TC12','paused'))
                assert paused['invariants']['counts']['holds']==0
                assert int(rt.sql('allocation','SELECT max(attempts) FROM allocation_jobs;'))==0
                scale('allocation-worker',1)
                final=browser(base,'pay-existing',folder/'confirmed',profiles/'allocation-pause',dict(user=original['user']))['booking']
                assert final['request']['request_id']==original['request']['request_id'] and final['checkout']['booking_status']=='confirmed'
                invariant(folder);return dict(original=original,confirmed=final)
            finally:scale('allocation-worker',1)
    allocation_pause.__name__='allocation-pause'

    def seat_outage(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            original=browser(base,'reserve',folder/'reserve',profiles/'seat-outage',dict(section='A',size=1))['booking']
            try:
                scale('payment-worker',0)
                pending=browser(base,'pay-pending',folder/'pending',profiles/'seat-outage',dict(user=original['user']))['booking']
                scale('seat-api',0);scale('payment-worker',1)
                wait(lambda:monitor()['pending']['count'],lambda n:n==1)
                work=wait(lambda:json.loads(rt.sql('payment',"SELECT json_agg(row_to_json(w)) FROM wy_work w WHERE kind='payment';")),lambda rows:any(w['failures']>0 for w in rows))
                save(folder/'outage-work.json',work)
                outage=save(folder/'outage.json',rt.capture(base,'TC13','outage'))
                read=save(folder/'outage-checkout.json',rt.request(base,'waiting-room/requests/'+original['request']['request_id']+'/checkout'))
                assert read['status']==503
                assert outage['invariants']['counts']['held']==1 and outage['invariants']['counts']['confirmed']==0
                scale('seat-api',1)
                final=wait(lambda:rt.api(base,'waiting-room/requests/'+original['request']['request_id']+'/checkout'),lambda c:c['booking_status']=='confirmed')
                stable(original['checkout'],final);assert len(final['payment_attempts'])==1
                browser(base,'inspect',folder/'confirmed',profiles/'seat-outage',dict(user=original['user'],status='confirmed',original=original))
                invariant(folder);save(folder/'final.json',final);return dict(original=original,pending=pending,confirmed=final)
            finally:
                scale('seat-api',1);scale('payment-worker',1)
    seat_outage.__name__='seat-outage'

    def storage(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            original=browser(base,'book',folder/'original-browser',profiles/'storage')['booking']
            # No active holds/actions/writers, as required by the original case.
            wait(lambda:monitor()['pending']['count'],lambda n:n==0)
            wait(lambda:rt.api(base,'dispatcher/status'),lambda s:s.get('current') is None)
            def records():
                result={}
                for db,table in [('seats','holds'),('seats','seats'),('payment','wy_payments'),('allocation','allocation_jobs')]:
                    result[db+'.'+table]=json.loads(rt.sql(db,f"SELECT COALESCE(json_agg(v ORDER BY v::text),'[]') FROM (SELECT to_jsonb(t) AS v FROM {table} t) s;"))
                result['queue']=rt.api(base,'waiting-room/queue')
                result['pvcs']={p['metadata']['name']:dict(uid=p['metadata']['uid'],volume=p['spec']['volumeName']) for p in json.loads(rt.k('get','pvc','-o','json',capture=True))['items']}
                return result
            # Checkout polling refreshes payment projection metadata; close browsers
            # before the authoritative pre-deletion snapshot, never ignore changes.
            before=save(folder/'records-before.json',records())
            pods=save(folder/'pods-before.json',json.loads(rt.k('get','pod','postgres-0','redis-0','-o','json',capture=True)))
            rt.k('delete','pod','postgres-0','redis-0','--wait=true')
            for name in ('postgres','redis'):rt.k('rollout','status','statefulset/'+name,'--timeout=180s')
            after=wait(records,lambda v:v==before,timeout=90)
            save(folder/'records-after.json',after)
            new=save(folder/'pods-after.json',json.loads(rt.k('get','pod','postgres-0','redis-0','-o','json',capture=True)))
            assert {p['metadata']['uid'] for p in pods['items']}.isdisjoint(p['metadata']['uid'] for p in new['items'])
            browser(base,'inspect',folder/'restored-browser',profiles/'storage',dict(user=original['user'],status='confirmed',original=original))
            later=browser(base,'book',folder/'new-browser',profiles/'storage-new',dict(name='After Storage Final',section='B',size=1))['booking']
            assert later['checkout']['booking_status']=='confirmed'
            invariant(folder);return dict(same_records_and_pvcs=True,original=original,new_booking=later)

    def browser_case(folder):
        fresh(folder)
        with rt.lab_connection() as base:
            result=browser(base,'recovery',folder/'browser',profiles/'recovery')
            assert rt.api(base,'waiting-room/queue')['count']==1
            invariant(folder);save(folder/'after.json',rt.capture(base,'TC25','after'))
            return result
    browser_case.__name__='browser'

    jobs=[(['TC-01','TC-02','TC-03','TC-04'],journeys),(['TC-05'],capacity),(['TC-06'],validation),(['TC-07'],flow),(['TC-08'],contention_case),(['TC-09'],compose),(['TC-10'],replacement),(['TC-11'],payment_pause),(['TC-12'],allocation_pause),(['TC-13'],seat_outage),(['TC-17'],storage),(['TC-25'],browser_case)]
    for ids,job in jobs:record(ids,job)
    summary['finished_at']=rt.utc();summary['status']='PASS' if summary['results'] and all(r['status']=='PASS' for r in summary['results'].values()) else 'FAIL'
    main_after=json.loads(rt.local.kubectl('get','deployments','-o','json',namespace='csc3104',capture=True))
    final={d['metadata']['name']:dict(uid=d['metadata']['uid'],spec=d['spec']) for d in main_after['items']}
    save(directory/'main-after.json',final)
    summary['main_specs_uids_unchanged']=final==json.loads((directory/'main-before.json').read_text())
    if not summary['main_specs_uids_unchanged']:summary['status']='FAIL'
    save(directory/'summary.json',summary)
    print('FINAL',summary['status'],directory,flush=True)
    return 0 if summary['status']=='PASS' else 2


if __name__=='__main__':
    sys.exit(main())
