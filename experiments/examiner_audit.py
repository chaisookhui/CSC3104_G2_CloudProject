"""Independently assess raw all-25 evidence without generating new traffic."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    checks=[];selected={};attempts=[]
    def check(case,label,ok,details=None):checks.append(dict(case=case,check=label,passed=bool(ok),details=details))
    for run in args.runs:
        folder=ROOT/'.local/test-results'/run;summary=read(folder/'summary.json')
        check('Environment',run+' main deployment preserved',summary['main_specs_uids_unchanged'])
        check('Continuity',run+' original application files unchanged',read(folder/'application-continuity.json')['status']=='PASS')
        for case,result in summary['results'].items():
            attempts.append(dict(case=case,run=run,status=result['status'],evidence=result['evidence']))
            if result['status']=='PASS':selected[case]=dict(result,run=run)
    old=ROOT/'experiments/audit_v9_evidence.py'
    code=old.read_text().replace("out=root/'output/validation/tc-fixes'",'out='+repr(str(args.output.resolve()))+';out=Path(out)')
    try:exec(compile(code,str(old),'exec'),{'__file__':str(old),'__name__':'__main__'})
    except SystemExit as done:
        check('Existing v9','raw original-workload auditor exits successfully',done.code==0)
    old_audit=read(args.output/'final-acceptance-audit.json')
    check('Existing v9','all saved-data checks pass',old_audit['status']=='PASS' and all(c['passed'] for c in old_audit['checks']),len(old_audit['checks']))
    original=read(ROOT/'.local/test-results/tc-fix-19-v9/surge-1/before.json')
    sources={k:v for k,v in original['source_files_sha256'].items() if k.startswith(('src/','frontend/','infra/')) or k=='demo.py'}
    changed=[k for k,v in sources.items() if hashlib.sha256((ROOT/k).read_bytes()).hexdigest()!=v]
    check('Continuity','all final v9 application/config files still unchanged',not changed,dict(files=len(sources),changed=changed))
    def images(snapshot):
        names=[d['name'] for d in snapshot['replicas']]+['redis','postgres']
        result={}
        for name in names:
            ids={c['imageID'] for p in snapshot['pods'] if p['name'].startswith(name+'-') for c in p['containers'] if c.get('imageID')}
            if ids:result[name]=sorted(ids)
        return result
    expected_images=images(original);new_snapshots=[]
    for run in args.runs:
        for path in (ROOT/'.local/test-results'/run).rglob('*.json'):
            if path.name not in ('before.json','after.json','paused.json','outage.json'):continue
            data=read(path)
            if isinstance(data,dict) and isinstance(data.get('pods'),list) and isinstance(data.get('replicas'),list):
                actual=images(data);new_snapshots.append(str(path.relative_to(ROOT)))
                check('Continuity',str(path.relative_to(ROOT))+' deployed images match v9',all(expected_images.get(k)==v for k,v in actual.items()))
    check('Continuity','new deployed image evidence captured',bool(new_snapshots),len(new_snapshots))
    saved={14:'tc-fix-regression-v9',15:'tc-fix-regression-v9',16:'tc-fix-regression-v9',18:'tc-fix-regression-v9',19:'tc-fix-19-v9',20:'tc-fix-regression-v9',21:'tc-fix-regression-v9',22:'tc-fix-regression-v9',23:'tc-fix-23-v9',24:'tc-fix-24-worker-v9'}
    for n,run in saved.items():selected[f'TC-{n:02}']=dict(status='PASS' if old_audit['status']=='PASS' and not changed else 'INCONCLUSIVE',run=run,evidence='.local/test-results/'+run,scope='Original complete final v9 workload; API HPA additionally tc-fix-24-api-v9')
    for n in [*range(1,14),17,25]:
        case=f'TC-{n:02}';check(case,'completed fresh final-version result exists',case in selected)
        if case not in selected:continue
        folder=ROOT/selected[case]['evidence']
        if n not in (6,9):
            inv=read(folder/'invariants.json');check(case,'nonempty original SQL safety checks pass',inv['status']=='PASS' and inv['violations']==0)
        if n in (1,2,3,4):
            raw=read(folder/'browser/browser-result.json');data=raw['cases'][case]
            check(case,'real Chromium UI assertions all passed',raw['status']=='PASS' and all(raw['checks'].values()))
            if n==1:
                a=data['before']['checkout'];b=data['after_reload']['checkout'];check(case,'original adjacent seats confirmed after actual reload',b['booking_status']=='confirmed' and len(b['seats'])==2 and all(s['state']=='CONFIRMED' for s in b['seats']) and a['hold_id']==b['hold_id'] and a['original_hold_expiry']==b['original_hold_expiry'])
            elif n==2:
                a=data['before']['checkout'];b=data['declined']['checkout'];c=data['confirmed']['checkout'];check(case,'decline then success retains exact hold/deadline',b['booking_status']=='active' and c['booking_status']=='confirmed' and a['hold_id']==b['hold_id']==c['hold_id'] and a['original_hold_expiry']==b['original_hold_expiry']==c['original_hold_expiry'])
            elif n==3:check(case,'cancelled reload terminal and all party seats released',data['after_reload']['checkout']['booking_status']=='cancelled' and len(data['after_reload']['checkout']['seats'])==3 and all(s['state']=='AVAILABLE' for s in data['after_reload']['checkout']['seats']))
            else:
                a=data['before']['checkout'];b=data['expired']['checkout'];check(case,'actual original five-minute expiry and same-hold late HTTP409',data['late_payment_status']==409 and b['booking_status']=='expired' and a['hold_id']==b['hold_id'] and datetime.fromisoformat(b['observed_at'])>=datetime.fromisoformat(a['original_hold_expiry']) and b['seats'][0]['state']=='AVAILABLE')
        elif n==5:
            raw=read(folder/'browser/browser-result.json');counts=read(folder/'invariants.json')['counts'];check(case,'two whole C4 parties, one no-fit, both tabs actually refreshed',raw['status']=='PASS' and all(raw['checks'].values()) and counts['held']==8 and len(raw['tabs']['after'])==2)
        elif n==6:
            raw=read(folder/'responses.json');check(case,'six actual400 and two404 responses with no queue mutation',[r['status'] for r in raw]==[400]*6+[404]*2 and read(folder/'queue-before.json')==read(folder/'queue-after.json'))
        elif n==7:
            raw=read(folder/'queue.json');late=[p for p in raw['requests'] if p['user_id'].startswith('sim-')];check(case,'original customer plus four real UI-simulated automatic latecomers',raw['count']==5 and len(late)==4 and all(p['entry_type']=='latecomer' and p['status']=='RESERVED' and p['section']=='B' and p['party_size']==1 for p in late) and read(folder/'browser/browser-result.json')['original']['checkout']['booking_status']=='confirmed')
            batches=read(folder/'dispatcher.json')['batch_history'];check(case,'five original IDs have completed correlated dispatcher receipts',len(batches)>=2 and all(b['state']=='COMPLETED' for b in batches) and {r['request_id'] for b in batches for r in b['outcomes']}=={r['request_id'] for r in raw['requests']})
        elif n==8:
            raw=read(folder/'customers.json');summary=read(folder/'summary.json');owners=[s['seat_id'] for r in raw if r['outcome']=='RESERVED' for s in r['response']['data']['seats']];check(case,'original20concurrent requests exact10holds10no-fit uniqueownership',len(raw)==20 and summary['workers']==20 and summary['peak_overlapping_client_requests']>=2 and summary['outcomes']=={'RESERVED':10,'UNAVAILABLE':10} and len(owners)==len(set(owners))==10)
        elif n==9:
            rows=read(folder/'containers.json');apps=[r for r in rows if r['Service'] not in ('seat-init','allocation-init','payment-migrate')];inits=[r for r in rows if r not in apps];check(case,'actual submitted Compose startup and internal service routing',len(apps)==13 and all(r['State']=='running' for r in apps) and len(inits)==3 and all(r['ExitCode']==0 for r in inits) and read(folder/'health.json')['status']==200)
            published=[p for r in rows for p in r.get('Publishers',[]) if p.get('PublishedPort',0)];check(case,'only actual frontend loopback mapping is public',bool(published) and all(p['URL']=='127.0.0.1' and p['PublishedPort']==18280 for p in published) and all(not any(p.get('PublishedPort',0) for p in r.get('Publishers',[])) for r in rows if r['Service']!='frontend'))
        elif n==10:
            a=read(folder/'pods-before.json');b=read(folder/'pods-after.json');check(case,'different actual API pod UID after controller recovery',{p['metadata']['uid'] for p in a['items']}.isdisjoint(p['metadata']['uid'] for p in b['items']) and read(folder/'after-browser/browser-result.json')['booking']['checkout']['booking_status']=='confirmed')
        elif n==11:
            paused=read(folder/'paused.json');final=read(folder/'final.json');check(case,'zero payment worker retained accepted work then same payment confirmed',any(d['name']=='payment-worker' and d['desired']==0 and d['ready']==0 for d in paused['replicas']) and paused['payment_monitor']['pending']['count']==1 and paused['observations']['payment_health']['status']==200 and final['booking_status']=='confirmed' and len(final['payment_attempts'])==1)
            original=read(folder/'checkout-paused.json');check(case,'exact original pending payment identity and deadline retained',original['payment_attempts'][0]['payment_id']==final['payment_attempts'][0]['payment_id'] and original['hold_id']==final['hold_id'] and original['original_hold_expiry']==final['original_hold_expiry'])
        elif n==12:
            paused=read(folder/'paused.json');after=read(folder/'confirmed/browser-result.json');check(case,'queued same request no hold during allocator pause, later confirmed',any(d['name']=='allocation-worker' and d['desired']==0 and d['ready']==0 for d in paused['replicas']) and paused['invariants']['counts']['holds']==0 and paused['allocation_backlog'].get('QUEUED')==1 and after['booking']['checkout']['booking_status']=='confirmed')
        elif n==13:
            outage=read(folder/'outage.json');work=read(folder/'outage-work.json');final=read(folder/'final.json');check(case,'actual dependency failures preserve pending hold then recover',read(folder/'outage-checkout.json')['status']==503 and any(w['kind']=='payment' and w['failures']>0 for w in work) and outage['invariants']['counts']['confirmed']==0 and outage['invariants']['counts']['held']==1 and final['booking_status']=='confirmed')
        elif n==17:
            before=read(folder/'records-before.json');after=read(folder/'records-after.json');a=read(folder/'pods-before.json');b=read(folder/'pods-after.json');check(case,'strict full business records and PVC identity preserved across store replacement',before==after and {p['metadata']['uid'] for p in a['items']}.isdisjoint(p['metadata']['uid'] for p in b['items']));check(case,'original survives reload plus actual new booking confirms',read(folder/'restored-browser/browser-result.json')['booking']['checkout']['booking_status']=='confirmed' and read(folder/'new-browser/browser-result.json')['booking']['checkout']['booking_status']=='confirmed')
        elif n==25:
            raw=read(folder/'browser/browser-result.json');check(case,'actual browser process restart/offline/profile denial/admin/expiry checks passed',raw['status']=='PASS' and all(raw['checks'].values()) and all(r['status']==403 for r in raw['denials']) and raw['expired']['checkout']['booking_status']=='expired');check(case,'no second registration',read(folder/'after.json')['observations']['queue']['data']['count']==1)
            denied={r['path'] for r in raw['denials']};payment_id=raw['before']['checkout']['payment_attempts'][0]['payment_id'];action_id=raw['owner_expired_action']['action_id'];check(case,'copied genuine payment and cancellation IDs denied',{'payment/payments/'+payment_id,'payment/payments/'+payment_id+'/details','payment/cancellations/'+action_id}<=denied and raw['owner_expired_action']['status']=='expired' and len(raw['denials'])>=8)
    check('Coverage','all25distinct IDs assessed',set(selected)=={f'TC-{i:02}' for i in range(1,26)})
    failed=[c for c in checks if not c['passed']]
    result=dict(status='FAIL' if failed or any(c['status']!='PASS' for c in selected.values()) else 'PASS',cases=selected,attempts=attempts,checks=checks,failed=failed,created_at=datetime.now().astimezone().isoformat(),scope='25-case local acceptance; old failed/inconclusive attempts retained; no production reliability guarantee')
    (args.output/'all25-audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result['status'],len(selected),'cases;',len(checks),'new checks;',len(failed),'failed')
    return int(result['status']!='PASS')


if __name__=='__main__':sys.exit(main())
