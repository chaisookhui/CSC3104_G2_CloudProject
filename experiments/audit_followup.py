"""Read-only saved-data audit; a valid failed experiment is retained as failed."""
import argparse
from control import evidence_state
from collections import Counter
import hashlib
import json
import math

from operations import hpa_cpu_evidence, hpa_transitions
from runtime import ROOT, RESULTS, utc, write_json
from workloads import digest, percentile, seat_fingerprint


def read(path):return json.loads(path.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',required=True)
    args=parser.parse_args()
    checks=[];pending=[];application=[];images=[];historical_interruptions=[]
    def check(path,name,value,details=None):
        checks.append(dict(path=str(path.relative_to(ROOT)),check=name,passed=bool(value),details=details))
    def close(left,right):
        return left is None and right is None or left is not None and right is not None and math.isclose(left,right,rel_tol=1e-8,abs_tol=1e-8)
    runs=[p for p in sorted(RESULTS.glob(args.prefix+'-*')) if p.is_dir() and 'preserve' not in p.name]
    for run in runs:
        for path in sorted(run.rglob('interrupted.json')):
            historical_interruptions.append(dict(run=run.name,path=str(path.relative_to(ROOT)),record=read(path)))
        if not (run/'summary.json').exists() and not (run/'comparison.json').exists():pending.append(run.name)
        for path in sorted(run.rglob('before.json')):
            before=read(path)
            sources={p:h for p,h in before['source_files_sha256'].items() if p.startswith(('src/','frontend/','infra/')) or p=='demo.py'}
            application.append(sources)
            image={name:sorted({c['imageID'] for p in before['pods'] if p['name'].startswith(name+'-') for c in p['containers']}) for name in [r['name'] for r in before['replicas']]}
            image.update({name:sorted({c['imageID'] for p in before['pods'] if p['name']==name+'-0' for c in p['containers']}) for name in ('redis','postgres')})
            images.append(image)
            check(path,'private lab namespace',before['namespace']=='csc3104-lab')
            check(path,'application sources match captured hashes',all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in sources.items()))
        for path in sorted(run.rglob('summary.json')):
            if evidence_state(run,path) in ('RUNNING','INTERRUPTED'):
                pending.append(dict(run=run.name,unit=str(path.parent),status='INTERRUPTED'))
                continue
            r=read(path);directory=path.parent
            if 'scheduled' in r and (directory/'arrivals.json').exists():
                rows=read(directory/'arrivals.json');rate,duration=r['rate'],r['duration']
                # Reconstruct independently from the declared stepped profile.
                q=duration/4
                schedule=([(i/rate,'baseline') for i in range(rate*duration)] if r['profile']=='constant' else
                    [(i/5,'baseline') for i in range(int(q*5))]+[(q+i/rate,'surge') for i in range(int(2*q*rate))]+
                    [(3*q+i/5,'baseline') for i in range(int(q*5))])
                check(path,'exact scheduled count and offsets',r['scheduled']==len(schedule)==len(rows) and
                    all(close(row['scheduled_seconds'],t) and row['phase']==phase for row,(t,phase) in zip(rows,schedule)))
                counts=dict(offered=len(rows),launched=sum('launched_seconds' in row for row in rows),
                    accepted=sum(row['outcome'].startswith('ACCEPTED') for row in rows),
                    rejected=sum(row['outcome']=='REJECTED' for row in rows),
                    timed_out=sum(row.get('response',{}).get('timed_out',False) or row.get('response',{}).get('error')=='TimeoutError' for row in rows),
                    generator_dropped=sum(row['outcome']=='DROPPED_GENERATOR' for row in rows))
                check(path,'reported traffic counts match raw rows',all(r[k]==v for k,v in counts.items()),counts)
                check(path,'achieved throughput includes response drain',close(r['achieved_registration_rps'],counts['accepted']/r['generator']['elapsed']))
                latencies=[row['response']['elapsed_ms'] for row in rows if 'response' in row]
                check(path,'raw latency quantiles match report',all(close(r['p'+str(n)+'_ms'],percentile(latencies,n)) for n in (50,95,99)))
                check(path,'submitted users remain unique',len({row['payload']['user_id'] for row in rows})==len(rows))
                lags=[row['launched_seconds']-row['scheduled_seconds'] for row in rows if 'launched_seconds' in row]
                faithful=len(lags)==len(rows) and bool(lags) and max(lags)<=1
                check(path,'delivery validity is honestly classified',r['timing_fidelity']==faithful)
                expected={row['stored_request_id'] for row in rows if row['outcome'].startswith('ACCEPTED') and row.get('stored_request_id')}
                if (directory/'registered-queue.json').exists():
                    registered={p['user_id']:p['request_id'] for p in read(directory/'registered-queue.json')}
                    check(path,'acknowledged and reconciled IDs match saved Redis records',all(
                        row.get('stored_request_id')==registered.get(row['payload']['user_id']) and
                        (row['outcome']!='ACCEPTED' or row['response']['data']['request_id']==row['stored_request_id'])
                        for row in rows if row['outcome'].startswith('ACCEPTED')))
                else:
                    check(path,'unavailable reconciliation cannot claim an identity PASS',r['status']!='PASS' and
                        bool(r.get('reconciliation_error')) and r.get('identity_verification_complete') is False)
                if r['status']=='PASS':
                    check(path,'PASS has complete accepted identities and clean SQL',len(expected)==len(schedule) and not r['missing_acknowledged_ids']
                          and r['duplicate_registration_ids']==0 and r['invariants']['violations']==0)
                if 'sustainable' in r:
                    sustainable=r['status']=='PASS' and r['http_failed']==0 and r['p95_ms']<=1000 and r['achieved_registration_rps']>=rate*.95
                    check(path,'capacity SLO classification unchanged',r['sustainable']==sustainable)
                    before=read(directory/'before.json')
                    check(path,'capacity fresh state and HPA off',not before['hpa']['items'] and
                        before['observations']['queue']['data']['requests']==[] and all(before['invariants']['counts'][k]==0 for k in ('holds','confirmed','held')))
                if r.get('admission'):
                    numbered=read(directory/'numbered-queue.json')
                    final=read(directory/'after.json')['observations']['queue']['data']['requests']
                    a={p['request_id']:p['queue_number'] for p in numbered};b={p['request_id']:p['queue_number'] for p in final}
                    if r['status']=='PASS':
                        check(path,'burst PASS has stable contiguous identities and terminal outcomes',a==b and set(a)==expected
                            and sorted(a.values())==list(range(1,len(a)+1)) and len(a)==len(numbered)==len(final)
                            and all(p['status'] in ('RESERVED','UNAVAILABLE','CONFIRMED','CANCELLED','EXPIRED') for p in final)
                            and r['admission']['elapsed_seconds']<=600 and r['admission']['invariants']['violations']==0)
            if 'trace_sha256' in r and (directory/'customers.json').exists():
                trace=read(directory/'trace.json');rows=read(directory/'customers.json')
                inventory=read(directory/'inventory-before.json')
                check(path,'40-party trace seed/count/batch and fingerprint',len(rows)==len(trace['customers'])==40 and trace['seed'] in range(42,52)
                    and trace['batch_size']==10 and r['trace_sha256']==digest(trace) and r['initial_fingerprint']==seat_fingerprint(inventory))
                check(path,'fixture bookings excluded from confirmed outcomes',r['confirmations']==sum(row['outcome']=='CONFIRMED' for row in rows)
                    and r['confirmed_trace_seats']==sum(row['party_size'] for row in rows if row['outcome']=='CONFIRMED')
                    and close(r['incremental_venue_utilization'],r['confirmed_trace_seats']/r['total_inventory']))
                batches=sorted(sorted(j['global_position'] for j in b['jobs']) for b in r['actual_batches'].values())
                check(path,'actual fixed batch boundaries and recorded policies',batches==[list(range(i,i+10)) for i in (1,11,21,31)]
                    and all(b['policy']==r['policy'] for b in r['actual_batches'].values()))
                for s in r['fairness']['sections']:
                    group=[g for g in r['groups'] if g['section']==s['section']]
                    rates=[g['reservation_rate'] for g in group]
                    interpretable=len(group)==4 and sum(rates)>0 and not any(g['unknown'] for g in group)
                    expected=sum(rates)**2/(4*sum(v*v for v in rates)) if interpretable else None
                    check(path,'Jain defined only with original coverage criteria / '+s['section'],s['interpretable']==interpretable and close(s['jain_reservation_rates'],expected))
        if (run/'comparison.json').exists():
            comparison=read(run/'comparison.json');entries=comparison['results']
            check(run/'comparison.json','ten seeds with both policies',Counter((e['seed'],e['policy']) for e in entries)==Counter((seed,p) for seed in range(42,52) for p in ('demand-cycle','fcfs')))
            for seed in range(42,52):
                pair=[e['result'] for e in entries if e['seed']==seed]
                check(run/'comparison.json','matched trace and initial inventory / '+str(seed),len(pair)==2 and
                      pair[0]['trace_sha256']==pair[1]['trace_sha256'] and pair[0]['initial_fingerprint']==pair[1]['initial_fingerprint'])
        for configuration in run.rglob('hpa-config.json'):
            cycle=configuration.parent
            if not (cycle/'summary.json').exists() or evidence_state(run,configuration) in ('RUNNING','INTERRUPTED'):continue
            r=read(cycle/'summary.json');phases=read(cycle/'phases.json');samples=read(cycle/'timeline.json');target=r['target']
            transitions=hpa_transitions(samples,target,*(phases[k]['monotonic'] for k in ('high','recovery','repeat')))
            cpu=hpa_cpu_evidence(samples,target,*(phases[k]['monotonic'] for k in ('high','recovery','repeat')))
            check(cycle/'summary.json','HPA raw Ready transitions and CPU match summary',digest(transitions)==digest(r['transitions']) and cpu==r['cpu'])
            if r['status']=='PASS':
                check(cycle/'summary.json','HPA PASS retains 600s window and genuine repeat',all(transitions[k] for k in ('baseline_one','scale_out','scale_in','repeat_scale_out'))
                    and cpu['exceeds_target'] and cpu['recovered_below_target'] and all(p['meets_delivery'] for p in r['phase_checks'].values())
                    and phases['repeat']['monotonic']-phases['recovery']['monotonic']>=600 and r['invariants']['violations']==0
                    and (target!='allocation-worker' or r['ten_minute_checkpoint']['window_met'] and r['fixed_api_four_ready_throughout']))
    output=ROOT/'output/validation'/args.prefix
    if application:check(output,'unchanged application/config sources throughout fresh trials',all(s==application[0] for s in application))
    if images:check(output,'unchanged deployed image IDs throughout fresh trials',all(s==images[0] for s in images))
    failed=[c for c in checks if not c['passed']]
    result=dict(status='FAIL' if failed else 'PASS',at=utc(),checks=checks,failed=failed,pending_or_interrupted=pending,
        historical_interruptions=historical_interruptions,
        scope='Saved-data consistency and support for claimed PASS outcomes; actual misses/inconclusive attempts remain unchanged. This is not a new workload or a recertification of the original 25 cases.')
    write_json(output/'raw-audit.json',result)
    print(result['status'],len(checks),'checks;',len(failed),'failed;',len(pending),'pending/interrupted')
    return bool(failed)


if __name__=='__main__':raise SystemExit(main())
