"""Independent acceptance audit of saved final-cohort rows and snapshots."""
from collections import Counter
from datetime import datetime,timedelta
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
base=root/'.local/test-results'
out=root/'output/validation/tc-fixes'
out.mkdir(parents=True,exist_ok=True)
checks=[]
terminal={'RESERVED','UNAVAILABLE','CONFIRMED','CANCELLED','EXPIRED'}
def read(path):return json.loads(path.read_text())
def check(case,name,passed,details=None):
    checks.append(dict(case=case,check=name,passed=bool(passed),details=details))
def arrivals(case,path,rate,duration,spike=False):
    rows=read(path/'arrivals.json')
    if spike:
        quarter=duration//4
        schedule=([(i/5,'baseline') for i in range(quarter*5)]+
                  [(quarter+i/rate,'surge') for i in range(2*quarter*rate)]+
                  [(3*quarter+i/5,'baseline') for i in range(quarter*5)])
    else:schedule=[(i/rate,'baseline') for i in range(rate*duration)]
    matched=len(rows)==len(schedule) and all(abs(row['scheduled_seconds']-t)<1e-9 and row['phase']==phase
        for row,(t,phase) in zip(rows,schedule))
    launched=[r for r in rows if 'launched_seconds' in r]
    lag=max((r['launched_seconds']-r['scheduled_seconds'] for r in launched),default=None)
    accepted=[r for r in rows if r['outcome'].startswith('ACCEPTED')]
    http_errors=sum(not 200<=r.get('response',{}).get('status',0)<300 for r in rows)
    check(case,path.name+' exact original schedule',matched,dict(expected=len(schedule),rows=len(rows)))
    check(case,path.name+' complete timely successful HTTP delivery',len(launched)==len(schedule)
          and len(accepted)==len(schedule) and http_errors==0 and lag is not None and lag<=1,
          dict(launched=len(launched),accepted=len(accepted),http_errors=http_errors,max_lag_seconds=lag))
    check(case,path.name+' unique submitted users',len({r['payload']['user_id'] for r in rows})==len(rows))
    ids=[r.get('stored_request_id') for r in accepted]
    check(case,path.name+' acknowledged IDs match stored IDs',len(set(ids))==len(ids) and None not in ids
          and all(r['response']['data']['request_id']==r['stored_request_id'] for r in accepted))
    attempts=[r.get('response',{}).get('upstream_attempts') for r in rows]
    check(case,path.name+' transparent bounded upstream attempts',
          all(type(n) is int and 1<=n<=2 for n in attempts),
          dict(known=sum(n is not None for n in attempts),
               recoveries=sum(n-1 for n in attempts if isinstance(n,int))))
    return set(ids)

# TC-19: original numbering is compared with final records, rather than trusting
# only the framework's stability boolean.
case='TC-19';run=base/'tc-fix-19-v9';summary=read(run/'summary.json')
check(case,'framework completed full cohort',summary['status']=='PASS' and len(summary['surge'])==3)
for n in (1,2,3):
    d=run/f'surge-{n}';expected=arrivals(case,d,100,40,True)
    initial=read(d/'numbered-queue.json')
    final=read(d/'after.json')['observations']['queue']['data']['requests']
    positions=lambda rows:{r['request_id']:r['queue_number'] for r in rows}
    before,after=positions(initial),positions(final)
    check(case,d.name+' stable exact queue identity/order',before==after and set(before)==expected
          and len(before)==len(initial)==len(final)==2100
          and all(type(p) is int for p in before.values()) and sorted(before.values())==list(range(1,2101)))
    check(case,d.name+' terminal outcomes within original deadline',all(p['status'] in terminal for p in final)
          and read(d/'admission.json')['elapsed_seconds']<=600)
    check(case,d.name+' SQL integrity',read(d/'admission.json')['invariants']['violations']==0
          and read(d/'after.json')['invariants']['violations']==0)
d=run/'mixed';mixed=read(d/'summary.json');rows=read(d/'customers.json');owners=[];valid=True
for r in rows:
    if r['outcome']=='RESERVED':
        seats=r['response']['data']['seats'];numbers=sorted(s['position_in_row'] for s in seats)
        valid &= (len(seats)==r['party_size'] and len({s['row'] for s in seats})==1
                  and numbers==list(range(numbers[0],numbers[0]+len(seats))))
        owners.extend(s['seat_id'] for s in seats)
check(case,'original mixed-party workload and safety',mixed['status']=='PASS' and len(rows)==40
      and mixed['workers']==32 and {r['party_size'] for r in rows}=={1,2,3,4}
      and mixed['peak_overlapping_client_requests']>=2 and valid and len(set(owners))==len(owners)<=10
      and mixed['invariants']['violations']==0)

# TC-23: nine equal workloads, three actually serving configurations, all metrics
# evidence retained. Exploratory overload points are reported as sustainable or
# not sustainable, never converted into a passing SLO by dropping requests.
case='TC-23';run=base/'tc-fix-23-v9';summary=read(run/'summary.json')
check(case,'three repeats at each replica count',Counter(r['replicas'] for r in summary['results'])=={1:3,2:3,4:3})
budgets=[]
for r in summary['results']:
    d=run/f"rate-50-repeat-{r['repeat']}-replicas-{r['replicas']}"
    arrivals(case,d,50,30)
    check(case,d.name+' actual serving/ready replicas and SQL',r['status']=='PASS'
        and r['distinct_serving_replicas']==r['replicas'] and r['observed_ready_replicas']==[r['replicas']]
        and r['resource_metrics_cover_all_replicas'] and not r['hpa_interference']
        and r['invariants']['violations']==0)
    before=read(d/'before.json');counts=before['invariants']['counts']
    check(case,d.name+' fresh equivalent inventory and no HPA',counts['holds']==counts['held']==counts['confirmed']==0
          and before['observations']['queue']['data']['requests']==[] and before['hpa']['items']==[]
          and before['config']['BATCH_SIZE']=='10' and before['config']['HOLD_TTL_SECONDS']=='300')
    budgets.append(dict(runtime=before['runtime'],resources={d['name']:d['resources'] for d in before['replicas']}))
check(case,'fixed cohort common host allocation and container budgets',all(b==budgets[0] for b in budgets))
capacity=read(base/'tc-fix-capacity-v9/summary.json')
check(case,'full initial capacity grid recorded',Counter((r['rate'],r['replicas']) for r in capacity['results'])==
      Counter((rate,n) for rate in (20,40,60,80,100) for n in (1,2,4)))
for r in capacity['results']:
    check(case,f"capacity {r['rate']}/s x{r['replicas']} integrity",not r['missing_acknowledged_ids']
          and r['duplicate_registration_ids']==0 and r['invariants']['violations']==0)
    sustainable=(r['status']=='PASS' and r['http_failed']==0 and r['p95_ms']<=1000
                 and r['achieved_registration_rps']>=r['rate']*.95)
    check(case,f"capacity {r['rate']}/s x{r['replicas']} SLO classification",r['sustainable']==sustainable)

upper_path=base/'tc-fix-capacity-upper-v9/summary.json'
if all(r['sustainable'] for r in capacity['results'] if r['rate']==100):
    upper=read(upper_path)
    check(case,'preplanned upper grid recorded after all100/s points passed',
          Counter((r['rate'],r['replicas']) for r in upper['results'])==
          Counter((200,n) for n in (1,2,4)))
    for r in upper['results']:
        check(case,f"upper capacity x{r['replicas']} identity and SQL",not r['missing_acknowledged_ids']
              and r['duplicate_registration_ids']==0 and r['invariants']['violations']==0)
        sustainable=(r['status']=='PASS' and r['http_failed']==0 and r['p95_ms']<=1000
                     and r['achieved_registration_rps']>=r['rate']*.95)
        check(case,f"upper capacity x{r['replicas']} honest SLO classification",r['sustainable']==sustainable)

# TC-24: reconstruct Ready transitions from raw Deployment snapshots, not HPA
# desired counts. The ten-minute worker checkpoint remains independent of any
# later observation.
for target,label in [('allocation-worker','worker'),('waiting-room','api')]:
    case='TC-24-'+label;run=base/('tc-fix-24-'+label+'-v9')
    summary=read(run/'summary.json');phases=read(run/'phases.json');samples=read(run/'timeline.json')
    expected=set()
    for name in ('baseline','high','repeat'):
        ids=arrivals(case,run/name,(1 if label=='worker' else 2) if name=='baseline' else 100,
                     120 if name=='baseline' else 180,name!='baseline')
        check(case,name+' IDs distinct across phases',not expected.intersection(ids));expected.update(ids)
    points=[]
    for s in samples:
        d=next((d for d in s.get('deployments',{}).get('items',[]) if d['metadata']['name']==target),None)
        if d:points.append((s['monotonic'],d.get('status',{}).get('readyReplicas',0)))
    high,recovery,repeat=(phases[n]['monotonic'] for n in ('high','recovery','repeat'))
    first=[n for t,n in points if t<high];busy=[n for t,n in points if high<=t<recovery]
    quiet=[n for t,n in points if recovery<=t<repeat];again=[n for t,n in points if t>=repeat]
    check(case,'actual ordered Ready cycle',bool(first) and all(n==1 for n in first)
          and any(n>1 for n in busy) and bool(quiet) and quiet[-1]==1 and any(n>1 for n in again))
    check(case,'full original observation durations',high-phases['baseline']['monotonic']>=120
          and recovery-high>=180 and repeat-recovery>=600 and samples[-1]['monotonic']>=repeat+180)
    final=read(run/'after.json')['observations']['queue']['data']['requests'];ids=[p['request_id'] for p in final]
    check(case,'global acknowledged identity and SQL',len(expected)==(19020 if label=='worker' else 19140)
          and expected.issubset(ids) and len(ids)==len(set(ids)) and summary['invariants']['violations']==0)
    check(case,'observed CPU target crossed and recovered',summary['cpu']['exceeds_target']
          and summary['cpu']['recovered_below_target'] and summary['status']=='PASS')
    offered_end=datetime.fromisoformat(read(run/'high/generator.json')['arrival_started_at'])+timedelta(seconds=180)
    original_window=[s for s in samples if offered_end<=datetime.fromisoformat(s['at'])<=offered_end+timedelta(seconds=600)]
    witnesses=[s for s in original_window if any(d['metadata']['name']==target
        and d.get('status',{}).get('readyReplicas')==1 for d in s.get('deployments',{}).get('items',[]))]
    if label=='worker':
        witnesses=[s for s in witnesses if s.get('waiting_queue',{}).get('queued_count')==0
            and 'backlog' in s and not any(s['backlog'].get(k,0) for k in ('QUEUED','IN_PROGRESS','RETRY','BLOCKED'))]
    check(case,'one Ready/drained witness within600s of actual offered-spike end',bool(witnesses),
          dict(first_seconds=(datetime.fromisoformat(witnesses[0]['at'])-offered_end).total_seconds() if witnesses else None))
    if label=='worker':
        checkpoint=read(run/'ten-minute-checkpoint.json');recovered=read(run/'recovery-queue.json')
        check(case,'original ten-minute drain and one Ready worker',checkpoint['window_met']
              and checkpoint['ready_replicas']==1 and not checkpoint['unresolved_ids']
              and all(p['status'] in terminal for p in recovered)
              and not any(checkpoint['backlog'].get(k,0) for k in ('QUEUED','IN_PROGRESS','RETRY','BLOCKED')))
        extra=read(run/'post-repeat/summary.json');final=read(run/'post-repeat/queue.json')
        check(case,'additional eventual repeat outcomes',extra['status']=='PASS'
              and {p['request_id'] for p in final}==expected and all(p['status'] in terminal for p in final)
              and extra['invariants']['violations']==0)

regression=read(base/'tc-fix-regression-v9/summary.json')
expected_regressions={*(f'{case}-r{n}' for case in ('TC14','TC15','TC20-active','TC20-expiry') for n in (1,2,3)),
    'TC16-1','TC16-2','TC16-4','TC18','TC21-reply','TC21-crash','TC22-redis','TC22-postgres','TC22-both'}
check('Regression','all original passing-case variants completed',regression.get('full_coverage') and
      {r['case'] for r in regression['results']}==expected_regressions
      and len(regression['results'])==len(expected_regressions) and regression['status']=='PASS')
for r in regression['results']:
    check('Regression',r['case']+' original assertions satisfied',r['status']=='PASS'
          and r.get('exit_code',0)==0,dict(scope=r.get('scope'),run=r.get('run',r.get('reused_run'))))
    if r['case'].startswith('TC16-') or r['case']=='TC18':
        comparison=read(base/r['run']/'comparison.json')
        entries=comparison['results']
        expected_pairs=Counter((seed,repeat,policy) for seed in (range(42,52) if r['case']=='TC18' else [42])
            for repeat in ([1] if r['case']=='TC18' else [1,2,3]) for policy in ('demand-cycle','fcfs'))
        check('Regression',r['case']+' original repetitions/seeds and inventory',
              Counter((e['seed'],e['repeat'],e['policy']) for e in entries)==expected_pairs
              and comparison['identical_initial_inventory'] and all(e['result']['status']=='PASS' for e in entries))
        for e in entries:
            child=base/r['run']/f"seed-{e['seed']}-repeat-{e['repeat']}-{e['policy']}"
            trace=read(child/'trace.json')
            before=read(child/'before.json')
            workers=next(d for d in before['replicas'] if d['name']=='allocation-worker')
            expected_workers=1 if r['case']=='TC18' else int(r['case'].split('-')[-1])
            customers=read(child/'customers.json')
            check('Regression',r['case']+child.name+' full40-party trace and SQL',
                  len(trace['customers'])==40 and trace['batch_size']==10
                  and trace['seed']==e['seed'] and e['result']['invariants']['violations']==0
                  and workers['ready']==workers['desired']==expected_workers
                  and len(customers)==40 and len({p['request_id'] for p in customers})==40
                  and all(p['outcome'] in ('CONFIRMED','UNAVAILABLE','EXPIRED','CANCELLED','REJECTED') for p in customers))
        if r['case']=='TC18':
            check('Regression','TC18 ten interpretable independent seeds /40 paired sections',
                  comparison['fairness']['independent_seeds']==10 and len(comparison['fairness']['pairs'])==40)

cohorts=[base/('tc-fix-'+name+'-v9') for name in ('19','23','capacity','24-worker','24-api')]
if upper_path.exists():cohorts.append(upper_path.parent)
source_signatures=[];image_signatures=[]
for cohort in cohorts:
    for p in list(cohort.rglob('before.json'))+list(cohort.rglob('after.json')):
        snapshot=read(p)
        # Report exports/regression orchestration were prepared while primary
        # performance runs continued; neither executes inside those arrivals/SUT.
        sources={k:v for k,v in snapshot['source_files_sha256'].items()
                 if k not in ('experiments/study_report.py','experiments/regression.py')}
        source_signatures.append(sources)
        apps=[d['name'] for d in snapshot['replicas']]
        images={app:sorted({c['imageID'] for pod in snapshot['pods'] if pod['name'].startswith(app+'-')
                           for c in pod['containers']}) for app in apps}
        for app in ('redis','postgres'):
            images[app]=sorted({c['imageID'] for pod in snapshot['pods'] if pod['name']==app+'-0'
                                for c in pod['containers']})
        image_signatures.append(images)
check('Reproducibility','application/generator/workload/config sources held fixed',
      len(source_signatures)>=60 and all(s==source_signatures[0] for s in source_signatures),
      dict(snapshots=len(source_signatures),excluded_non_executing_modules=
           ['experiments/study_report.py','experiments/regression.py']))
check('Reproducibility','same deployed image IDs throughout final performance cohorts',
      all(s==image_signatures[0] for s in image_signatures),dict(snapshots=len(image_signatures)))

failed=[c for c in checks if not c['passed']]
result=dict(status='PASS' if not failed else 'FAIL',checks=checks,failed=failed,
            scope='Raw acceptance audit of final cohorts. Earlier failures remain in their original folders.')
(out/'final-acceptance-audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(result['status'],len(checks),'checks;',len(failed),'failed')
raise SystemExit(bool(failed))
