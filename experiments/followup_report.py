"""Measured follow-up synthesis, article text and slide figures; no deployment."""
import argparse
from control import evidence_state
import csv
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from statistics import mean

from runtime import ROOT, RESULTS, utc, write_json
from workloads import digest, percentile
from followup import verify_recorded


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def csvfile(path, rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields or ['status']);writer.writeheader()
        writer.writerows({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)


def avg(rows,key):
    values=[r[key] for r in rows if r.get(key) is not None]
    return mean(values) if values else None


def fmt(value,digits=3):
    return 'undefined / pending' if value is None else f'{value:.{digits}f}'


def burst_summary(traffic):
    """Keep interrupted attempts out of completed-trial denominators."""
    summaries=[]
    for peak in (100,150,200):
        attempts=[r for r in traffic if r['label']=='Fresh follow-up' and r['profile']=='spike'
                  and r['duration']==40 and r['rate']==peak]
        complete=[r for r in attempts if r['status'] not in ('INTERRUPTED','RUNNING','PENDING')]
        elapsed=[r['admission']['elapsed_seconds'] for r in complete if r.get('admission')]
        summaries.append(dict(peak=peak,planned_offers=100+20*peak,complete_trials=len(complete),
            retained_partial_attempts=len(attempts)-len(complete),
            passing_trials=sum(r['status']=='PASS' and r['delivery_valid'] for r in complete),
            accepted=sum(r['accepted'] for r in complete),offered=sum(r['offered'] for r in complete),
            mean_admission_seconds=mean(elapsed) if elapsed else None,
            max_admission_seconds=max(elapsed) if elapsed else None,
            raw=[r['raw'] for r in complete]))
    return summaries


def recorded_identity_verification(result,directory):
    """Old summaries predate the flag; the saved queue proves the read occurred."""
    explicit=result.get('identity_verification_complete')
    return bool(explicit) if explicit is not None else (directory/'registered-queue.json').is_file()


def same_study(command, run):
    """Match a replacement to its original protocol, allowing fresh run/trace paths."""
    manifest=read(run/'run.json',{})
    if not manifest:return False
    recorded=manifest.get('arguments') or manifest.get('commands',[{}])[-1].get('arguments',{})
    arguments=command[1:command.index('--run')]
    if '--trace' in arguments:
        index=arguments.index('--trace')+1
        actual=recorded.get('trace')
        if not actual or read(Path(arguments[index]))!=read(Path(actual)):return False
        arguments[index]=actual
    try:verify_recorded(arguments,manifest)
    except (ValueError,KeyError,IndexError):return False
    return True


def scheduler(run, label):
    comparison=read(run/'comparison.json')
    entries=comparison['results'] if comparison else read(run/'partial-results.json',[])
    by_seed={};policies=[];groups=[];pairs=[];fair=[]
    for entry in entries:
        r=entry['result'];seed=entry['seed'];policy=entry['policy']
        child=run/entry.get('evidence_path',f'seed-{seed}-repeat-{entry["repeat"]}-{policy}')
        if evidence_state(run,child) in ('RUNNING','INTERRUPTED'):continue
        trace=read(child/'trace.json');customers=read(child/'customers.json',[])
        if not trace:
            continue
        waits=[c['decision_wait_seconds'] for c in customers if c.get('decision_wait_seconds') is not None]
        row=dict(label=label,scenario=trace['scenario'],run=run.name,seed=seed,policy=policy,status=r['status'],
            offered=r['customers'],requested_seats=r['requested_seats'],confirmed_parties=r['confirmations'],
            confirmed_seats=r['confirmed_trace_seats'],incremental_utilization=r['incremental_venue_utilization'],
            inventory_seats=r['total_inventory'],fixture_occupied=r['initial_occupied'],
            median_wait_seconds=percentile(waits,50),p95_wait_seconds=percentile(waits,95),measured_waits=len(waits),
            trace_verified=digest(trace)==r['trace_sha256'],inventory_fingerprint=r['initial_fingerprint'],
            batch_boundaries_match=r['batch_boundaries_match'],trace_sha256=r['trace_sha256'],
            raw=str((child/'summary.json').relative_to(ROOT)))
        policies.append(row)
        by_seed.setdefault((seed,entry['repeat']),{})[policy]=(r,row)
        for section in 'ABCD':
            for size in range(1,5):
                g=next((g for g in r['groups'] if g['section']==section and g['party_size']==size),None)
                groups.append(dict(label=label,scenario=trace['scenario'],run=run.name,seed=seed,policy=policy,
                    section=section,party_size=size,offered=g['offered'] if g else 0,
                    reserved=g['reserved'] if g else None,confirmed=g['confirmed'] if g else None,
                    reservation_rate=g['reservation_rate'] if g else None,unknown=g['unknown'] if g else None,
                    median_wait_seconds=g['median_wait_seconds'] if g else None,
                    p95_wait_seconds=g['p95_wait_seconds'] if g else None,raw=row['raw']))
    for (seed,repeat),pair in sorted(by_seed.items()):
        if set(pair)!={'demand-cycle','fcfs'}:continue
        d,dr=pair['demand-cycle'];f,fr=pair['fcfs']
        matched=all(r['status']=='PASS' and r['trace_verified'] and r['batch_boundaries_match'] for r in (dr,fr)) and (
            dr['trace_sha256']==fr['trace_sha256'] and dr['inventory_fingerprint']==fr['inventory_fingerprint'])
        common=dict(label=label,scenario=dr['scenario'],run=run.name,seed=seed,repeat=repeat,matched=matched,
                    demand_raw=dr['raw'],fcfs_raw=fr['raw'])
        delta=dict(**common,offered_per_policy=dr['offered'],inventory_seats=dr['inventory_seats'])
        for key in ('confirmed_parties','confirmed_seats','incremental_utilization','median_wait_seconds','p95_wait_seconds'):
            delta[key+'_delta']=dr[key]-fr[key] if matched and dr[key] is not None and fr[key] is not None else None
        seed_fair=[]
        for section in 'ABCD':
            left=next((s for s in d['fairness']['sections'] if s['section']==section),{})
            right=next((s for s in f['fairness']['sections'] if s['section']==section),{})
            covered=matched and left.get('complete_size_coverage') and right.get('complete_size_coverage') and (
                left.get('unknown_customers')==right.get('unknown_customers')==0)
            jain=covered and left.get('interpretable') and right.get('interpretable')
            row=dict(**common,section=section,gap_interpretable=bool(covered),jain_interpretable=bool(jain),
                demand_offered_by_size={str(g['party_size']):g['offered'] for g in d['groups'] if g['section']==section},
                fcfs_offered_by_size={str(g['party_size']):g['offered'] for g in f['groups'] if g['section']==section},
                gap_delta=left['reservation_rate_gap']-right['reservation_rate_gap'] if covered else None,
                jain_delta=left['jain_reservation_rates']-right['jain_reservation_rates'] if jain else None,
                demand_jain=left.get('jain_reservation_rates') if jain else None,
                fcfs_jain=right.get('jain_reservation_rates') if jain else None)
            seed_fair.append(row);fair.append(row)
        delta.update(gap_delta=avg(seed_fair,'gap_delta'),jain_delta=avg(seed_fair,'jain_delta'),
            gap_sections=sum(r['gap_interpretable'] for r in seed_fair),jain_sections=sum(r['jain_interpretable'] for r in seed_fair))
        pairs.append(delta)
    return policies,groups,pairs,fair


def hpa_timing(run,label):
    samples=read(run/'timeline.json')
    if samples is None:
        samples=[json.loads(line) for line in (run/'timeline.jsonl').read_text().splitlines()] if (run/'timeline.jsonl').exists() else []
    phases=read(run/'phases.json',{});config=read(run/'hpa-config.json',{})
    result=read(run/'summary.json',{})
    target=config.get('metadata',{}).get('name')
    if not samples or not target:return [],dict(label=label,run=run.name,status=result.get('status','PENDING'))
    start=samples[0]['monotonic'];points=[]
    for s in samples:
        deployment=next((d for d in s.get('deployments',{}).get('items',[]) if d['metadata']['name']==target),None)
        hpa=next((h for h in s.get('hpa',{}).get('items',[]) if h['metadata']['name']==target),{})
        cpu=next(((m['resource'].get('current') or {}).get('averageUtilization') for m in ((hpa.get('status') or {}).get('currentMetrics') or []) if m.get('resource',{}).get('name')=='cpu'),None)
        points.append(dict(label=label,run=run.name,at=s['at'],monotonic=s['monotonic'],seconds=s['monotonic']-start,
            target=target,ready=deployment.get('status',{}).get('readyReplicas',0) if deployment else None,
            desired=hpa.get('status',{}).get('desiredReplicas'),cpu_percent_of_request=cpu,
            waiting_queued=s.get('waiting_queue',{}).get('queued_count'),
            worker_unfinished=sum(s['backlog'].get(k,0) for k in ('QUEUED','IN_PROGRESS','RETRY','BLOCKED')) if 'backlog' in s else None,
            raw=str((run/'timeline.json').relative_to(ROOT))))
    sequence=[]
    for p in points:
        if p['ready'] is not None and (not sequence or sequence[-1]!=p['ready']):sequence.append(p['ready'])
    high=phases.get('high',{}).get('monotonic');recovery=phases.get('recovery',{}).get('monotonic');repeat=phases.get('repeat',{}).get('monotonic')
    generator=read(run/'high/generator.json',{})
    # Convert wall-time generator arrival epoch to the same monotonic axis.
    offer_end=None
    if generator.get('arrival_started_at'):
        offer_end=start+(datetime.fromisoformat(generator['arrival_started_at'])-datetime.fromisoformat(samples[0]['at'])).total_seconds()+180
    scale_out=next((p['monotonic'] for p in points if high is not None and recovery is not None and high<=p['monotonic']<recovery and (p['ready'] or 0)>1),None)
    scale_in=next((p['monotonic'] for p in points if scale_out is not None and offer_end is not None and p['monotonic']>=max(offer_end,scale_out) and p['ready']==1),None)
    drain=next((p['monotonic'] for p in points if target=='allocation-worker' and recovery is not None and p['monotonic']>=recovery and (repeat is None or p['monotonic']<repeat) and p['worker_unfinished']==0 and p['waiting_queued']==0),None)
    summary=dict(label=label,run=run.name,target=target,status=result.get('status','PENDING'),
        actual_ready_sequence=sequence,peak_ready=max((p['ready'] for p in points if p['ready'] is not None),default=None),
        first_scale_out_seconds_from_high=scale_out-high if scale_out is not None else None,
        high_offer_end_monotonic=offer_end,
        one_ready_seconds_after_offer_end=scale_in-offer_end if scale_in is not None else None,
        one_ready_within_600s_from_offer_end=scale_in-offer_end<=600 if scale_in is not None else None,
        backlog_drain_seconds_after_offer_end=drain-offer_end if drain is not None and offer_end is not None else None,
        repeat_scale_out=result.get('transitions',{}).get('repeat_scale_out'),
        ten_minute_window_met=result.get('ten_minute_checkpoint',{}).get('window_met') if result.get('ten_minute_checkpoint') else result.get('transitions',{}).get('scale_in'),
        extended_cycle_status=result.get('extended_cycle_status'),
        sql_violations=result.get('invariants',{}).get('violations'),
        sample_interval_note='Transitions and drain times are first observed samples, not exact event times; CPU is Metrics Server windowed.',
        raw=str((run/'summary.json').relative_to(ROOT)))
    return points,summary


def traffic_bins(run,label):
    bins={}
    for path in sorted(run.rglob('arrivals.json')):
        generator=read(path.parent/'generator.json',{})
        if not generator.get('arrival_started_at'):continue
        epoch=datetime.fromisoformat(generator['arrival_started_at'])
        for row in read(path,[]):
            for key,offset in (('offered',row.get('scheduled_seconds')),
                               ('launched',row.get('launched_seconds')),
                               ('accepted',row.get('completed_seconds') if row.get('outcome','').startswith('ACCEPTED') else None)):
                if offset is None:continue
                at=(epoch+timedelta(seconds=offset)).timestamp()
                second=int(at//5)*5
                record=bins.setdefault((str(path.parent),second),dict(label=label,run=run.name,trial=path.parent.name,
                    bin_start=datetime.fromtimestamp(second,epoch.tzinfo).isoformat(),bin_seconds=5,
                    offered=0,launched=0,accepted=0,raw=str(path.relative_to(ROOT))))
                record[key]+=1
    return list(bins.values())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or ROOT/'output/validation'/args.prefix/'report'
    output.mkdir(parents=True,exist_ok=True)
    baselines=['tc-fix-regression-v9-TC18','tc-fix-19-v9','tc-fix-capacity-v9','tc-fix-capacity-upper-v9','tc-fix-24-api-v9','tc-fix-24-worker-v9']
    fresh=sorted(p for p in RESULTS.glob(args.prefix+'-*') if p.is_dir() and 'preserve' not in p.name)
    runs=[(RESULTS/name,'Original baseline') for name in baselines]+[(p,'Fresh follow-up') for p in fresh]
    policies=[];groups=[];pairs=[];fair=[];traffic=[];hpa=[];timelines={};attempts=[];bins=[];provenance=[]
    for run,label in runs:
        if not run.exists():continue
        bins+=traffic_bins(run,label)
        for before in sorted(run.rglob('before.json')):
            snapshot=read(before,{})
            sources={name:value for name,value in snapshot.get('source_files_sha256',{}).items()
                     if name.startswith(('src/','frontend/','infra/')) or name=='demo.py'}
            pods=snapshot.get('pods',[])
            provenance.append(dict(label=label,run=run.name,trial=before.parent.name,at=snapshot.get('captured_at'),
                commit=snapshot.get('commit'),working_source_sha256=snapshot.get('working_source_sha256'),
                application_source_sha256=digest(sources) if sources else None,
                images={p['name']:[c.get('imageID') for c in p.get('containers',[])] for p in pods} if isinstance(pods,list) else None,
                resources=snapshot.get('replicas'),config=snapshot.get('config'),runtime=snapshot.get('runtime'),raw=str(before.relative_to(ROOT))))
        summary=read(run/'summary.json',{});comparison=read(run/'comparison.json',{})
        attempts.append(dict(label=label,run=run.name,status=summary.get('status',comparison.get('status','INTERRUPTED' if (run/'interrupted.json').exists() else 'PENDING')),
            interruption=read(run/'interrupted.json'),raw=str(run.relative_to(ROOT))))
        if comparison or (run/'partial-results.json').exists() and '-18-' in run.name:
            a,b,c,d=scheduler(run,label);policies+=a;groups+=b;pairs+=c;fair+=d
        for path in sorted(run.rglob('summary.json')):
            r=read(path)
            if evidence_state(run,path) in ('RUNNING','INTERRUPTED'):continue
            if 'scheduled' not in r or 'rate' not in r:continue
            identity_source='explicit_flag' if r.get('identity_verification_complete') is not None else 'legacy_registered_queue_snapshot'
            r['identity_verification_complete']=recorded_identity_verification(r,path.parent)
            generator=r.get('generator',{})
            delivery_valid=(r.get('timing_fidelity') and r['scheduled']==r.get('offered')==r.get('launched') and r.get('generator_dropped')==0)
            traffic.append(dict(label=label,run=run.name,trial=path.parent.name,
                **{key:r.get(key) for key in ('status','rate','duration','profile','replicas','repeat','scheduled','offered','launched','accepted','rejected','timed_out','generator_dropped','reconciled_unknowns','http_failed','max_launch_lag_seconds','p95_launch_lag_seconds','achieved_registration_rps','p50_ms','p95_ms','p99_ms','sustainable','identity_verification_complete','reconciliation_error','after_capture_error')},
                delivery_valid=bool(delivery_valid),identity_verification_source=identity_source,
                peak_in_flight=generator.get('peak_in_flight'),pool_capacity=generator.get('capacity'),
                cpu_fraction=generator.get('cpu_seconds',0)/generator['elapsed'] if generator.get('elapsed') else None,
                accepted_id_duplicates=r.get('duplicate_registration_ids'),missing_ids=len(r.get('missing_acknowledged_ids',[])),
                sql_violations=r.get('invariants',{}).get('violations'),admission=r.get('admission'),raw=str(path.relative_to(ROOT))))
        for path in sorted(run.rglob('arrivals.json')):
            if (path.parent/'summary.json').exists() and evidence_state(run,path) not in ('RUNNING','INTERRUPTED'):continue
            rows=read(path,[]);schedule=read(path.parent/'schedule.json',{})
            if not schedule:continue
            generator=read(path.parent/'generator.json',{})
            waits=[r['response']['elapsed_ms'] for r in rows if r.get('response',{}).get('elapsed_ms') is not None]
            lags=[r['launched_seconds']-r['scheduled_seconds'] for r in rows if 'launched_seconds' in r]
            before=read(path.parent/'before.json',{})
            api_deployment=next((d for d in before.get('replicas',[]) if d['name']=='waiting-room'),{})
            exact=len(rows)==schedule['planned_requests'] and all(
                abs(row['scheduled_seconds']-planned['scheduled_seconds'])<1e-9 and row['phase']==planned['phase']
                for row,planned in zip(rows,schedule['arrivals']))
            drops=sum(r.get('drop_reason')=='concurrency_capacity_exhausted' for r in rows)
            traffic.append(dict(label=label,run=run.name,trial=path.parent.name,status='INTERRUPTED',
                rate=schedule['rate'],duration=schedule['duration'],profile=schedule['profile'],
                replicas=api_deployment.get('desired') if schedule['profile']=='constant' and schedule['duration']==30 else None,repeat=None,
                scheduled=schedule['planned_requests'],offered=len(rows),launched=len(lags),
                accepted=sum(r.get('outcome','').startswith('ACCEPTED') for r in rows),
                rejected=sum(r.get('outcome')=='REJECTED' for r in rows),
                timed_out=sum(r.get('response',{}).get('timed_out',False) for r in rows),
                generator_dropped=drops,
                reconciled_unknowns=None,http_failed=None,max_launch_lag_seconds=max(lags) if lags else None,
                p95_launch_lag_seconds=percentile(lags,95),achieved_registration_rps=None,
                p50_ms=percentile(waits,50),p95_ms=percentile(waits,95),p99_ms=percentile(waits,99),sustainable=None,
                delivery_valid=bool(exact and len(lags)==len(rows) and lags and max(lags)<=1 and drops==0),
                peak_in_flight=generator.get('peak_in_flight'),pool_capacity=generator.get('capacity'),
                cpu_fraction=generator.get('cpu_seconds',0)/generator['elapsed'] if generator.get('elapsed') else None,
                achieved_acknowledged_rps=sum(r.get('outcome')=='ACCEPTED' for r in rows)/generator['elapsed'] if generator.get('elapsed') else None,
                admission=None,raw=str(path.relative_to(ROOT)),
                interpretation='Partial attempt; acceptance/reconciliation and SQL analysis did not complete.'))
        for phases in run.rglob('phases.json'):
            cycle=phases.parent
            if evidence_state(run,phases) in ('RUNNING','INTERRUPTED'):continue
            points,row=hpa_timing(cycle,label)
            row['run']=run.name;hpa.append(row);timelines[run.name]=points
    plan=read(ROOT/'output/validation'/args.prefix/'plan.json',{})
    reruns=[]
    for command in plan.get('commands',[]):
        run=command[command.index('--run')+1]
        attempt=next((r for r in attempts if r['run']==run),None)
        replacement=next((r for r in reversed(attempts) if r['label']=='Fresh follow-up' and r['run']!=run
            and r['status'] not in ('PENDING','INTERRUPTED','REPLACED') and same_study(command,RESULTS/r['run'])),None) if (
                attempt is None or attempt['status'] in ('PENDING','INTERRUPTED')) else None
        if attempt is None:
            attempts.append(dict(label='Fresh follow-up',run=run,status='REPLACED' if replacement else 'PENDING',
                interruption=None,replaced_by=replacement['run'] if replacement else None,raw=str((RESULTS/run).relative_to(ROOT))))
        elif replacement:
            attempt['replaced_by']=replacement['run']
        if replacement:continue
        if attempt is None or attempt['status'] in ('PENDING','INTERRUPTED'):
            retry=command.copy();retry[retry.index('--run')+1]=run+'-retry-a'
            reruns.append(dict(run=run,status=attempt['status'] if attempt else 'PENDING',command=retry))
    write_json(output/'pending-reruns.json',reruns)
    csvfile(output/'scheduler-policies.csv',policies);csvfile(output/'scheduler-strata.csv',groups)
    csvfile(output/'scheduler-seed-deltas.csv',pairs);csvfile(output/'scheduler-section-pairs.csv',fair)
    csvfile(output/'traffic-trials.csv',traffic);csvfile(output/'hpa-summary.csv',hpa)
    csvfile(output/'traffic-timestamped.csv',bins)
    csvfile(output/'hpa-timeline.csv',[r for rows in timelines.values() for r in rows]);write_json(output/'attempts.json',attempts)
    csvfile(output/'lab-provenance.csv',provenance)
    scheduler_summary=[]
    matched_ids={(r['run'],r['seed']) for r in pairs if r['matched']}
    for scenario in ('F1','F2','F3','F6'):
        selected=[r for r in pairs if r['scenario']==scenario and r['matched']]
        sections=[r for r in fair if r['scenario']==scenario]
        row=dict(scenario=scenario,label='Original baseline' if scenario=='F1' else 'Fresh follow-up',matched_seeds=len(selected),
            offered_per_policy_per_seed=40,inventory_seats=selected[0]['inventory_seats'] if selected else None,
            confirmed_parties_delta=avg(selected,'confirmed_parties_delta'),confirmed_seats_delta=avg(selected,'confirmed_seats_delta'),
            utilization_delta=avg(selected,'incremental_utilization_delta'),median_wait_delta=avg(selected,'median_wait_seconds_delta'),
            p95_wait_delta=avg(selected,'p95_wait_seconds_delta'),gap_delta=avg(selected,'gap_delta'),jain_delta=avg(selected,'jain_delta'),
            gap_seed_denominator=sum(r['gap_delta'] is not None for r in selected),jain_seed_denominator=sum(r['jain_delta'] is not None for r in selected),
            gap_section_denominator=sum(r['gap_interpretable'] for r in sections),jain_section_denominator=sum(r['jain_interpretable'] for r in sections),
            by_section={s:dict(gap_pairs=sum(r['gap_interpretable'] for r in sections if r['section']==s),
                jain_pairs=sum(r['jain_interpretable'] for r in sections if r['section']==s),
                mean_gap_delta=avg([r for r in sections if r['section']==s],'gap_delta'),
                mean_jain_delta=avg([r for r in sections if r['section']==s],'jain_delta')) for s in 'ABCD'})
        row['policy_means']={p:{k:avg([r for r in policies if r['scenario']==scenario and r['policy']==p and (r['run'],r['seed']) in matched_ids],k)
            for k in ('confirmed_parties','confirmed_seats','incremental_utilization','median_wait_seconds','p95_wait_seconds')}
            for p in ('demand-cycle','fcfs')}
        row['original_tradeoff_recurs']=('PENDING' if not selected else 'UNDEFINED_FAIRNESS' if row['jain_delta'] is None else
            'YES_DESCRIPTIVE' if row['confirmed_parties_delta']>0 and row['jain_delta']<0 else 'NO_ON_MEAN_PAIRED_EFFECT')
        scheduler_summary.append(row)
    write_json(output/'scheduler-summary.json',scheduler_summary)
    # Fairness deltas are computed within each seed first. Scenario fairness
    # means average seed means, using only represented interpretable sections.
    # Rate metrics per size use their own nonzero offered denominators.
    stratum_pairs=[]
    for scenario in ('F1','F2','F3','F6'):
        for section in 'ABCD':
            for size in range(1,5):
                selected=[r for r in groups if r['scenario']==scenario and r['section']==section and r['party_size']==size and (r['run'],r['seed']) in matched_ids]
                deltas=[];denominators=[]
                for seed in range(42,52):
                    pair={r['policy']:r for r in selected if r['seed']==seed}
                    if set(pair)!={'demand-cycle','fcfs'}:continue
                    d,f=pair['demand-cycle'],pair['fcfs']
                    if d['offered'] and f['offered'] and d['unknown']==f['unknown']==0 and any(p['scenario']==scenario and p['seed']==seed and p['matched'] for p in pairs):
                        deltas.append(d['reservation_rate']-f['reservation_rate']);denominators.append(d['offered'])
                stratum_pairs.append(dict(scenario=scenario,section=section,party_size=size,interpretable_matched_pairs=len(deltas),
                    mean_reservation_rate_delta=mean(deltas) if deltas else None,offered_denominators_by_matched_seed=denominators))
    csvfile(output/'reservation-rate-pairs.csv',stratum_pairs)
    capacity=[]
    for replicas in (1,2,4):
        valid=[r for r in traffic if r['label']=='Fresh follow-up' and r['replicas']==replicas and r['delivery_valid'] and r['sustainable'] is not None]
        passing=[r for r in valid if r['sustainable']]
        misses=[r for r in valid if not r['sustainable']]
        highest=max((r['rate'] for r in passing),default=None);first=min((r['rate'] for r in misses),default=None)
        capacity.append(dict(replicas=replicas,highest_passing_tested_rate=highest,first_valid_miss_rate=first,
            trials_at_highest=sum(r['rate']==highest for r in valid),passing_trials_at_highest=sum(r['rate']==highest for r in passing),
            trials_at_first_miss=sum(r['rate']==first for r in valid),
            slo_miss_trials_at_first_miss=sum(r['rate']==first for r in misses),
            completed_attempts_at_highest=sum(r['label']=='Fresh follow-up' and r['replicas']==replicas and r['rate']==highest and r['status']!='INTERRUPTED' for r in traffic),
            completed_attempts_at_first_miss=sum(r['label']=='Fresh follow-up' and r['replicas']==replicas and r['rate']==first and r['status']!='INTERRUPTED' for r in traffic),
            incomplete_reconciliation_trials=sum(not r.get('identity_verification_complete') for r in valid),
            incomplete_reconciliation_at_first_miss=sum(r['rate']==first and not r.get('identity_verification_complete') for r in valid),
            invalid_delivery_attempts=sum(
                r['label']=='Fresh follow-up' and r['replicas']==replicas and not r['delivery_valid'] for r in traffic)))
    write_json(output/'capacity-summary.json',capacity)
    bursts=burst_summary(traffic)
    write_json(output/'burst-summary.json',bursts)
    diagnostics=[]
    for r in traffic:
        if r['label']!='Fresh follow-up' or r['delivery_valid']:continue
        rows=read(ROOT/r['raw'].replace('summary.json','arrivals.json'),[])
        errors={}
        for row in rows:
            response=row.get('response',{})
            if response.get('error'):
                key=f"{response.get('error')} errno={response.get('os_errno')}: {response.get('error_message')}"
                errors[key]=errors.get(key,0)+1
        diagnostics.append(dict(run=r['run'],trial=r['trial'],scheduled=r['scheduled'],launched=r['launched'],
            dropped=r['generator_dropped'],max_lag_seconds=r['max_launch_lag_seconds'],peak_in_flight=r['peak_in_flight'],
            pool_capacity=r['pool_capacity'],cpu_fraction=r['cpu_fraction'],transport_errors=errors,
            max_dispatch_lag_seconds=max((row['dispatch_seconds']-row['scheduled_seconds'] for row in rows if 'dispatch_seconds' in row),default=None),
            max_headers_after_dispatch_seconds=max((row['launched_seconds']-row['dispatch_seconds'] for row in rows if 'dispatch_seconds' in row and 'launched_seconds' in row),default=None),
            capacity_interpretation='INVALID_DELIVERY: cannot interpret as a server capacity boundary. '
                'Pool-exhaustion drops are explicit; lag without drops can include event-loop scheduling and connection acquisition. '
                'Use saved arrivals and host/CPU/transport samples to distinguish these observed constraints; do not assume a cause.',
            raw=r['raw']))
    write_json(output/'delivery-diagnostics.json',diagnostics)
    lines=['# Follow-up evaluation — observed evidence', '', f'Generated {utc()}. Original 25-case results remain unchanged.', '',
        'All deltas are Demand-Cycle minus FCFS within the same seed. Fairness means average within-seed section means; no significance claim. '
        'Unrepresented sizes are missing. Jain requires all four sizes, known outcomes and positive service; gaps require all four sizes and known outcomes. '
        'F6 fixture bookings are excluded from all customer and incremental-utilization numerators. '
        'Incremental venue utilization = customer-confirmed seats / total physical inventory; per-trial denominators are retained.', '',
        '| Scenario / evidence | Matched seeds / 10 | Δ confirmed parties / 40 | Δ seats | Δ utilization (pp) | Δ Jain (seed; section n) | Δ gap (seed; section n) | F1 trade-off recurs? |',
        '|---|---:|---:|---:|---:|---|---|---|']
    for r in scheduler_summary:
        lines.append(f"| {r['scenario']} — {r['label']} | {r['matched_seeds']} | {fmt(r['confirmed_parties_delta'])} | {fmt(r['confirmed_seats_delta'])} | {fmt(100*r['utilization_delta'] if r['utilization_delta'] is not None else None)} | {fmt(r['jain_delta'])} ({r['jain_seed_denominator']}; {r['jain_section_denominator']}) | {fmt(r['gap_delta'])} ({r['gap_seed_denominator']}; {r['gap_section_denominator']}) | {r['original_tradeoff_recurs']} |")
    lines += ['', 'The complete per-policy counts, 16 section/size denominators per trace, within-seed deltas, metric-specific pair counts, waits and raw paths are in the scheduler CSV/JSON files.', '',
        '| API replicas | Fresh highest passing tested rate | First valid tested miss | Valid trials at highest (passing) | Valid trials at first miss (misses) | Invalid-delivery attempts |',
        '|---:|---:|---:|---:|---:|---:|']
    for r in capacity:lines.append(f"| {r['replicas']} | {r['highest_passing_tested_rate'] or 'PENDING'} | {r['first_valid_miss_rate'] or 'None observed / pending'} | {r['trials_at_highest']} ({r['passing_trials_at_highest']}) | {r['trials_at_first_miss']} ({r['slo_miss_trials_at_first_miss']}) | {r['invalid_delivery_attempts']} |")
    lines += ['', 'Highest passing rate means at least one observed complete passing trial, not a stable capacity estimate. '
        'Non-monotonic and mixed repeated outcomes are retained. A valid-delivery HTTP/latency miss can still have incomplete '
        'accepted-ID reconciliation; its acknowledged count is a lower bound, and it is not a completed correctness pass. '
        'Per-trial identity verification and all denominators are retained in traffic-trials.csv and capacity-summary.json.']
    lines += ['', '| TC-19 fresh peak | Planned offers / trial | Complete trials | Passing trials | Retained partial attempts | Accepted / offered (complete trials) | Mean admission time (s) |',
        '|---:|---:|---:|---:|---:|---|---:|']
    for r in bursts:
        lines.append(f"| {r['peak']}/s | {r['planned_offers']} | {r['complete_trials']} | {r['passing_trials']} | {r['retained_partial_attempts']} | {r['accepted']} / {r['offered']} | {fmt(r['mean_admission_seconds'],1)} |")
    lines += ['', '| HPA run / label | Status (original window) | Actual Ready sequence | Peak | Scale-out (s) | Offer-end → 1 Ready (s) | Backlog drain (s) | Repeat scale-out | Later diagnostic |',
        '|---|---|---|---:|---:|---:|---:|---|---|']
    for r in hpa:
        drain=fmt(r.get('backlog_drain_seconds_after_offer_end'),1) if r['target']=='allocation-worker' else 'N/A'
        diagnostic=r.get('extended_cycle_status') or 'Not needed'
        lines.append(f"| {r['run']} / {r['label']} | {r['status']} | {r.get('actual_ready_sequence')} | {r.get('peak_ready')} | {fmt(r.get('first_scale_out_seconds_from_high'),1)} | {fmt(r.get('one_ready_seconds_after_offer_end'),1)} | {drain} | {r.get('repeat_scale_out')} | {diagnostic} |")
    lines += ['', 'CPU-based Kubernetes HPA is evaluated only in the private local Kind cluster. It targets 50% of CPU requests, '
        '1–4 pods, one added pod/30s, one removed pod/60s, and 60s downscale stabilization. API request is 50m; worker request is 200m '
        '(500m limit). Worker tests keep four fixed Ready API replicas. Cached Metrics Server CPU and sampled Ready transitions do not establish cloud or production scalability. '
        'The original 600-second recovery status is retained even when later diagnostic recovery occurs.', '',
        'Traffic delivery is valid only with the exact schedule, all launches, no generator drops and maximum launch lag ≤1s. '
        'Capacity additionally requires all accepted/reconciled, zero HTTP errors, P95 ≤1,000ms, achieved accepted throughput ≥95% of offer, '
        'all fixed replicas serving, correct IDs and zero SQL violations. A valid miss retains the observed failure; an invalid generator attempt cannot bound server capacity.', '',
        '## Attempts and raw evidence', '', '| Label | Run | Status | Raw directory |', '|---|---|---|---|']
    for r in attempts:lines.append(f"| {r['label']} | {r['run']} | {r['status']} | `{r['raw']}` |")
    lines += ['', 'See traffic-trials.csv for offered/launched/accepted/reconciled/rejected/timed-out/dropped counts, generator headroom, launch lag, p50/p95/p99, admission deadlines and SQL checks. '
        'See cohort plan.json, *-command.json and *.log for exact commands. Each trial before.json/after.json records revision, source hashes, image IDs and resource settings. '
        'Original baseline sources are explicitly labelled; incomplete or interrupted attempts remain retained.']
    if reruns:
        lines += ['', '## Pending or interrupted rerun commands', '',
            'Run sequentially after preserving any current lab evidence. Fresh retry IDs preserve existing attempts.']
        import subprocess
        for row in reruns:lines += ['', f"{row['run']} — {row['status']}", '', '```powershell',subprocess.list2cmdline(row['command']),'```']
    (output/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    article='In private Kind, Demand-Cycle and FCFS were compared using 40-party traces, batch 10, one worker and 120s holds. '
    for r in scheduler_summary[1:]:
        article+=f"{r['scenario']} ({r['matched_seeds']} seed pairs) changed confirmed parties/Jain by {fmt(r['confirmed_parties_delta'],1)}/{fmt(r['jain_delta'])} ({r['jain_section_denominator']} interpretable section pairs). "
    article+='Fixture bookings were excluded and missing strata left Jain undefined. The original F1 trade-off did not recur on mean paired effects; F3 nevertheless had a worse rate gap despite higher Jain. '
    article+='At 1/2/4 API replicas, highest observed passing 30s offers were '+ '/'.join(str(r['highest_passing_tested_rate'] or 'pending') for r in capacity)+' requests/s; per-trial pass fractions and non-monotonic misses remain explicit. '
    fresh_hpa=[r for r in hpa if r['label']=='Fresh follow-up']
    article+=f"{sum(r['status']=='PASS' for r in fresh_hpa)}/{len(fresh_hpa)} fresh CPU-based HPA cycles met the original 600s recovery and repeated-scale-out criteria. "
    article+=f"Admission bursts passed {sum(r['passing_trials'] for r in bursts)}/{sum(r['complete_trials'] for r in bursts)} complete trials at tested peaks 100–200/s. "
    article+='Admission includes terminal unavailable outcomes, not thousands of bookings. Incomplete reconciliation and invalid load delivery remain unclaimed; these local observations do not establish production capacity.'
    (output/'ARTICLE_EVALUATION.md').write_text(article+'\n',encoding='utf-8')
    compact=['# Compact article results', '', 'Fresh follow-up measurements; original F1 is a separate retained baseline.', '',
        '| Study | Setting | Evidence count | Observed result |', '|---|---|---:|---|']
    for r in scheduler_summary[1:]:
        compact.append(f"| TC-18 {r['scenario']} | 40 parties, DC − FCFS | {r['matched_seeds']} seed pairs | Δ parties {fmt(r['confirmed_parties_delta'],1)}, Δ seats {fmt(r['confirmed_seats_delta'],1)}, Δ Jain {fmt(r['jain_delta'])} (section n={r['jain_section_denominator']}) |")
    for target,name in (('waiting-room','API'),('allocation-worker','Worker')):
        selected=[r for r in fresh_hpa if r['target']==target]
        compact.append(f"| TC-24 {name} | CPU HPA, original 600s recovery | {len(selected)} full cycles | {sum(r['status']=='PASS' for r in selected)} PASS; peak Ready {max((r['peak_ready'] for r in selected),default='pending')}; repeated scale-out |")
    for r in capacity:
        compact.append(f"| TC-23 | {r['replicas']} API replicas, 30s | {r['trials_at_highest']} valid-delivery trials at highest | Highest observed pass {r['highest_passing_tested_rate']} req/s ({r['passing_trials_at_highest']} passing); first observed valid-delivery miss {r['first_valid_miss_rate']} req/s |")
    for r in bursts:
        compact.append(f"| TC-19 | {r['peak']}/s peak, {r['planned_offers']} offers | {r['complete_trials']} complete trials | {r['passing_trials']} PASS; maximum admission {fmt(r['max_admission_seconds'],1)}s / 600s |")
    compact+=['', 'Jain requires represented sizes 1–4, known outcomes and positive service. See RESULTS.md and scheduler CSVs for metric-specific seed/section denominators and waits. '
        'Admission means terminal processing, including unavailable parties. Capacity maxima describe observed trials; partial HTTP acknowledgements are lower bounds and invalid delivery does not establish a capacity boundary. '
        'All raw run/trial paths are in traffic-trials.csv, scheduler-policies.csv, hpa-summary.csv and lab-provenance.csv.']
    (output/'ARTICLE_TABLE.md').write_text('\n'.join(compact)+'\n',encoding='utf-8')
    plot(output,policies,pairs,traffic,hpa,timelines,bins)
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file() and p.name!='SHA256.json'}
    write_json(output/'SHA256.json',manifest)
    print(output/'RESULTS.md')


def plot(output,policies,pairs,traffic,hpa,timelines,bins):
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    def save(fig,name):
        fig.savefig(output/(name+'.png'),dpi=200,bbox_inches='tight')
        fig.savefig(output/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(12,4),layout='constrained')
    for ax,key,title in zip(axes,('confirmed_parties_delta','incremental_utilization_delta','jain_delta'),
                           ('Δ confirmed parties / 40','Δ incremental utilization (pp)','Δ Jain (interpretable sections)')):
        ax.axhline(0,color='gray',ls='--',lw=1)
        for x,scenario in enumerate(('F1','F2','F3','F6')):
            values=[r[key] for r in pairs if r['matched'] and r['scenario']==scenario and r.get(key) is not None]
            if key=='incremental_utilization_delta':values=[v*100 for v in values]
            ax.scatter([x+(i-(len(values)-1)/2)*.015 for i in range(len(values))],values,color='#536c82' if scenario=='F1' else '#147d92',alpha=.6,s=20)
            if values:ax.scatter([x],[mean(values)],marker='_',s=300,color='#111827',zorder=4)
            ax.annotate(f'n={len(values)}',(x,.97),xycoords=('data','axes fraction'),ha='center',va='top',fontsize=8)
        ax.set(title=title,xticks=range(4),xticklabels=['F1\nOriginal','F2\nFresh','F3\nFresh','F6\nFresh'],xlim=(-.5,3.5));ax.margins(y=.15);ax.grid(axis='y',alpha=.2)
    fig.suptitle('Matched seed effects: Demand-Cycle − FCFS (dots = seed deltas; bars = means)')
    save(fig,'scheduler-paired-comparison')
    fig,grid=plt.subplots(2,2,figsize=(12,7),layout='constrained')
    axes=list(grid.flat)
    for replicas,color in ((1,'#147d92'),(2,'#c57637'),(4,'#6f55a1')):
        for label,marker in (('Original baseline','x'),('Fresh follow-up','o')):
            selected=[r for r in traffic if r['replicas']==replicas and r['label']==label]
            for r in selected:
                achieved=r['achieved_registration_rps'] if r['achieved_registration_rps'] is not None else r.get('achieved_acknowledged_rps')
                if achieved is None:continue
                partial=r['status']=='INTERRUPTED' or r.get('identity_verification_complete') is False
                point_marker='^' if partial else marker
                axes[0].scatter(r['rate'],achieved,marker=point_marker,color=color,
                    facecolors='none' if not r['delivery_valid'] and marker=='o' else color,
                    label=f'{replicas} replicas / unreconciled HTTP ACKs' if partial else f'{replicas} replicas / {label}' if r is selected[0] else None)
                axes[1].scatter(r['rate'],r['p95_ms'],marker=point_marker,color=color)
                if r.get('http_failed') is not None and r.get('launched'):
                    axes[2].scatter(r['rate'],100*r['http_failed']/r['launched'],marker=point_marker,color=color)
                if r.get('max_launch_lag_seconds') is not None:
                    axes[3].scatter(r['rate'],r['max_launch_lag_seconds'],marker=point_marker,color=color,
                        facecolors='none' if not r['delivery_valid'] and marker=='o' else color)
    axes[0].plot([0,300],[0,300],'--',color='gray',label='Offered = achieved')
    axes[0].plot([0,300],[0,285],':',color='gray',label='95% rate threshold')
    axes[0].set(xlabel='Offered requests/s',ylabel='Observed registrations/s incl. response drain',title='Offered versus achieved',xlim=(0,315),ylim=(0,None))
    handles,labels=axes[0].get_legend_handles_labels();unique=dict(zip(labels,handles))
    axes[0].legend(unique.values(),unique.keys(),fontsize=7)
    axes[1].axhline(1000,color='gray',ls='--',label='Original 1,000ms threshold')
    axes[1].set_yscale('log')
    axes[1].set(xlabel='Offered requests/s',ylabel='P95 HTTP latency (ms, log scale)',title='Measured tail latency');axes[1].legend(fontsize=8)
    axes[2].axhline(0,color='gray',ls='--',lw=.8,label='Zero HTTP failures required')
    axes[2].set_yscale('symlog',linthresh=.1)
    axes[2].set(xlabel='Offered requests/s',ylabel='HTTP failures / launched (%, symlog)',title='HTTP failures remain explicit')
    axes[2].set_ylim(-.02,100)
    axes[2].set_yticks([0,.1,1,10,100],labels=['0','0.1','1','10','100'])
    axes[2].legend(fontsize=8)
    axes[3].axhline(1,color='gray',ls='--',label='Original 1s launch-lag limit')
    axes[3].set_yscale('symlog',linthresh=.05)
    axes[3].set(xlabel='Offered requests/s',ylabel='Maximum header-send lag (s, symlog)',title='Generator delivery validity')
    max_lag=max((r.get('max_launch_lag_seconds') or 0 for r in traffic if r.get('replicas') in (1,2,4)),default=1)
    axes[3].set_ylim(0,max(1.5,max_lag*1.5))
    axes[3].legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2)
    fig.suptitle('TC-23: × original; ○ fresh (hollow = invalid delivery); △ unreconciled ACK lower bound',fontsize=10)
    save(fig,'traffic-offered-achieved')
    for row in hpa:
        points=timelines[row['run']]
        if not points:continue
        fig,axes=plt.subplots(4,1,figsize=(10,9),sharex=True,layout='constrained')
        xs=[p['seconds']/60 for p in points]
        for key,style in (('ready','-'),('desired','--')):
            axes[0].step(xs,[p[key] if p[key] is not None else float('nan') for p in points],where='post',ls=style,label=key)
        axes[0].set(ylabel='Replicas',yticks=range(5),title=f"{row['label']} · {row['run']} · {row['status']}");axes[0].legend()
        axes[1].plot(xs,[p['cpu_percent_of_request'] if p['cpu_percent_of_request'] is not None else float('nan') for p in points],color='#147d92')
        axes[1].axhline(50,color='gray',ls='--');axes[1].set(ylabel='HPA CPU (% request)')
        axes[2].plot(xs,[p['waiting_queued'] if p['waiting_queued'] is not None else float('nan') for p in points],label='Waiting-room queued')
        axes[2].plot(xs,[p['worker_unfinished'] if p['worker_unfinished'] is not None else float('nan') for p in points],label='Unfinished allocation jobs')
        axes[2].set(ylabel='Backlog',ylim=(0,None));axes[2].legend()
        epoch=datetime.fromisoformat(points[0]['at'])
        traffic=[r for r in bins if r['run']==row['run']]
        grouped={}
        for r in traffic:
            t=int(datetime.fromisoformat(r['bin_start']).timestamp())
            g=grouped.setdefault(t,dict(offered=0,accepted=0))
            for key in g:g[key]+=r[key]/5
        if grouped:
            end=max(max(grouped),int(datetime.fromisoformat(points[-1]['at']).timestamp()//5)*5)
            for t in range(min(grouped),end+5,5):grouped.setdefault(t,dict(offered=0,accepted=0))
        for key in ('offered','accepted'):
            axes[3].step([(t-epoch.timestamp())/60 for t in sorted(grouped)],
                [grouped[t][key] for t in sorted(grouped)],where='post',label=key)
        axes[3].set(ylabel='Traffic /s (5s bins)',xlabel='Minutes since first monitor sample');axes[3].legend()
        run=RESULTS/row['run'];phases=read(run/'phases.json',{})
        for ax in axes:
            ax.grid(alpha=.2)
            for name,phase in phases.items():
                x=(phase['monotonic']-points[0]['monotonic'])/60
                ax.axvline(x,color='gray',ls=':',alpha=.5)
                if ax is axes[0]:ax.annotate(name,(x,.98),xycoords=('data','axes fraction'),va='top',fontsize=7)
        save(fig,'hpa-'+row['run'])
    fresh=sorted((r for r in hpa if r['label']=='Fresh follow-up'),
                 key=lambda r:(r['target']!='waiting-room',r['run']))
    if fresh:
        fig,axes=plt.subplots(2,2,figsize=(12,6.5),layout='constrained')
        maximum=max((p.get('cpu_percent_of_request') or 0 for r in fresh for p in timelines[r['run']]),default=100)
        for ax,row in zip(axes.flat,fresh):
            points=timelines[row['run']];start=points[0]['monotonic']
            xs=[(p['monotonic']-start)/60 for p in points]
            phases=read((ROOT/row['raw']).parent/'phases.json',{})
            for name in ('high','repeat'):
                if name in phases:
                    x=(phases[name]['monotonic']-start)/60
                    ax.axvspan(x,x+phases[name].get('duration',180)/60,color='#d7a44a',alpha=.13)
            if 'recovery' in phases:
                end=(phases['recovery']['monotonic']+600-start)/60
                ax.axvline(end,color='#64748b',ls=':',lw=1,label='600s recovery end')
            ax.step(xs,[p['ready'] for p in points],where='post',color='#147d92',lw=1.8,label='Actual Ready')
            ax.step(xs,[p['desired'] for p in points],where='post',color='#334155',ls='--',lw=1,label='HPA desired')
            cpu=ax.twinx()
            cpu.plot(xs,[p.get('cpu_percent_of_request') if p.get('cpu_percent_of_request') is not None else float('nan') for p in points],
                     color='#c57637',alpha=.65,lw=1,label='CPU / request')
            cpu.axhline(50,color='#c57637',ls=':',lw=.7)
            cpu.set(ylabel='CPU (% of request)',ylim=(0,max(100,maximum*1.15)))
            target='API' if row['target']=='waiting-room' else 'Worker'
            repeat=row['run'].rsplit('-r',1)[-1]
            ax.set(title=f"{target} cycle {repeat}: {row['status']} · scale-out {fmt(row.get('first_scale_out_seconds_from_high'),1)}s",
                   ylabel='Replicas',xlabel='Minutes since baseline observation',ylim=(0,4.5),yticks=range(5))
            ax.text(.98,.04,f"1 Ready: {fmt(row.get('one_ready_seconds_after_offer_end'),1)}s after first spike offer-end",
                    transform=ax.transAxes,ha='right',va='bottom',fontsize=8,
                    bbox=dict(facecolor='white',edgecolor='none',alpha=.75,pad=2))
            ax.grid(axis='y',alpha=.2)
        for ax in list(axes.flat)[len(fresh):]:ax.set_visible(False)
        axes.flat[0].legend(fontsize=7,loc='upper center')
        fig.suptitle('Fresh CPU-based HPA in private Kind · shaded spikes · orange CPU (dotted target 50%)',fontsize=11)
        save(fig,'hpa-fresh-overview')


if __name__=='__main__':main()
