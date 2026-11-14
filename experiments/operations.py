"""API replica comparison and optional CPU autoscaling in the private Kind lab."""
import json
import time
from collections import Counter
from runtime import LAB, api, capture, invariants, k, lab_connection, local, setup_lab, utc, write_json
from workloads import arrival_schedule, registration_load
from observability import monitor, preflight, ready_replicas


def hpa_object(name):
    if name not in ('waiting-room','allocation-worker'): raise ValueError('Unexpected HPA target')
    return dict(apiVersion='autoscaling/v2',kind='HorizontalPodAutoscaler',metadata=dict(name=name),
        spec=dict(scaleTargetRef=dict(apiVersion='apps/v1',kind='Deployment',name=name),
            minReplicas=1,maxReplicas=4,
            metrics=[dict(type='Resource',resource=dict(name='cpu',target=dict(type='Utilization',averageUtilization=50)))],
            behavior=dict(scaleUp=dict(stabilizationWindowSeconds=0,
                policies=[dict(type='Pods',value=1,periodSeconds=30)]),
                scaleDown=dict(stabilizationWindowSeconds=60,
                policies=[dict(type='Pods',value=1,periodSeconds=60)]))))


def autoscale(directory,install_metrics=False,disable=False):
    if disable:
        k('delete','hpa','waiting-room','allocation-worker','--ignore-not-found')
        result=dict(status='PASS',enabled=False)
    else:
        if install_metrics:
            # Fixed private Kind context; never reads or changes the user's current context.
            local.kubectl('apply','-f','https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.1/components.yaml',namespace=None)
            local.kubectl('patch','deployment','metrics-server','--type=json','-p',json.dumps([
                dict(op='add',path='/spec/template/spec/containers/0/args/-',value='--kubelet-insecure-tls')]),namespace='kube-system')
            local.kubectl('rollout','status','deployment/metrics-server','--timeout=180s',namespace='kube-system')
        local.kubectl('wait','--for=condition=Available','apiservice/v1beta1.metrics.k8s.io','--timeout=90s',namespace=None)
        # Lab-only calibration: four idle workers used ~84-100m in diagnostics.
        # A 50m request at 60% targeted just 30m total at one replica. A 200m
        # request at 50% allows genuine idle demand to converge to one worker.
        k('set','resources','deployment/allocation-worker','--requests=cpu=200m,memory=96Mi')
        k('rollout','status','deployment/allocation-worker','--timeout=180s')
        for name in ('waiting-room','allocation-worker'):local.apply_object(hpa_object(name),LAB)
        result=dict(status='PASS',enabled=True,hpa=json.loads(k('get','hpa','-o','json',capture=True)),
            interpretation='Configured HPA, not proof of a scale-out. Record actual replicas, metrics and events under sustained load. '
            'The insecure kubelet TLS flag is restricted to this local Kind installation.')
    write_json(directory/'summary.json',result);return result


def hpa_transitions(samples, target, first_high, recovery, repeat):
    """Require actual Ready transitions in phase order, not desired counts alone."""
    points=[]
    for s in samples:
        d=next((d for d in s.get('deployments',{}).get('items',[]) if d['metadata']['name']==target),None)
        if d: points.append((s['monotonic'],d['status'].get('readyReplicas',0)))
    baseline=[n for t,n in points if t<first_high]
    high=[n for t,n in points if first_high<=t<recovery]
    low=[n for t,n in points if recovery<=t<repeat]
    again=[n for t,n in points if t>=repeat]
    baseline_one=bool(baseline) and all(n==1 for n in baseline)
    scale_out=baseline_one and any(n>1 for n in high)
    scale_in=scale_out and bool(low) and low[-1]==1
    return dict(baseline_one=baseline_one,scale_out=scale_out,scale_in=scale_in,
        repeat_scale_out=scale_in and any(n>1 for n in again),points=points)


def hpa_cpu_evidence(samples,target,high,recovery,repeat):
    values=[]
    for s in samples:
        h=next((h for h in s.get('hpa',{}).get('items',[]) if h['metadata']['name']==target),{})
        metrics=(h.get('status') or {}).get('currentMetrics') or []
        cpu=next(((m['resource'].get('current') or {}).get('averageUtilization') for m in metrics
                  if (m.get('resource') or {}).get('name')=='cpu'),None)
        if cpu is not None:values.append((s['monotonic'],cpu))
    loaded=[v for t,v in values if high<=t<recovery]
    low=[v for t,v in values if repeat-60<=t<repeat]
    return dict(high_peak_utilization=max(loaded) if loaded else None,
                final_recovery_mean_utilization=sum(low)/len(low) if low else None,
                exceeds_target=bool(loaded) and max(loaded)>50,
                recovered_below_target=bool(low) and sum(low)/len(low)<50,
                samples=len(values))


def accepted_ids(directory,names):
    return {row['stored_request_id'] for name in names
            for row in json.loads((directory/name/'arrivals.json').read_text())
            if row['outcome'].startswith('ACCEPTED') and row.get('stored_request_id')}


def worker_drain_diagnostic(base,directory,phases,samples,limit=2400):
    """Additional observation only; never replaces the 600-second criterion."""
    phases['extended_drain']=dict(at=utc(),monotonic=time.monotonic(),rate=0,maximum_seconds=limit)
    write_json(directory/'phases.json',phases)
    deadline=time.monotonic()+limit
    terminal={'RESERVED','UNAVAILABLE','CONFIRMED','CANCELLED','EXPIRED'}
    expected=accepted_ids(directory,('baseline','high'))
    result=dict(drained=False,maximum_additional_seconds=limit,observation_errors=[])
    while time.monotonic()<deadline:
        latest=samples[-1] if samples else {}
        waiting=latest.get('waiting_queue',{})
        if (time.monotonic()-latest.get('monotonic',0)<30 and waiting.get('phase')=='OPEN'
                and waiting.get('queued_count')==0 and 'backlog' in latest and
                all(latest['backlog'].get(state,0)==0 for state in ('QUEUED','IN_PROGRESS','RETRY','BLOCKED'))):
            try:queue=api(base,'waiting-room/queue')['requests']
            except RuntimeError as error:
                result['observation_errors'].append(dict(at=utc(),message=str(error)))
                write_json(directory/'extended-drain.json',result)
                time.sleep(1)
                continue
            missing=expected-{p['request_id'] for p in queue}
            if missing:
                result['missing_accepted_ids']=sorted(missing)
                break
            if all(p['status'] in terminal for p in queue):
                write_json(directory/'extended-drained-queue.json',queue)
                result.update(drained=True,drained_at=utc(),drained_monotonic=time.monotonic(),
                              terminal_counts=dict(Counter(p['status'] for p in queue)))
                break
        time.sleep(1)
    if result['drained']:
        phases['idle_observation']=dict(at=utc(),monotonic=time.monotonic(),rate=0,duration=300)
        write_json(directory/'phases.json',phases)
        end=time.monotonic()+300
        while time.monotonic()<end:time.sleep(min(1,max(0,end-time.monotonic())))
    result['finished_at']=utc()
    write_json(directory/'extended-drain.json',result)
    return result


def hpa_trial(directory,target):
    setup_lab(True,'demand-cycle',300,10)
    k('delete','hpa','waiting-room','allocation-worker','--ignore-not-found')
    local.kubectl('wait','--for=condition=Available','apiservice/v1beta1.metrics.k8s.io','--timeout=90s',namespace=None)
    if target=='allocation-worker':
        # Establish the API dependency before attaching worker HPA. It stays
        # fixed throughout this cycle, so incoming traffic can exercise worker
        # demand without confounding it with a saturated one-pod API tier.
        k('scale','deployment/waiting-room','--replicas=4')
        k('rollout','status','deployment/waiting-room','--timeout=180s')
        if not ready_replicas('waiting-room',4):raise RuntimeError('Worker study requires four ready fixed API replicas')
        k('set','resources','deployment/allocation-worker','--requests=cpu=200m,memory=96Mi')
        k('rollout','status','deployment/allocation-worker','--timeout=180s')
    if not ready_replicas(target,1): raise RuntimeError('HPA trial requires one ready baseline replica')
    phases={}
    loads=[]
    try:
      with lab_connection() as base:
        write_json(directory/'preflight.json',preflight(base))
        write_json(directory/'before.json',capture(base,'TC-24-'+target,'before'))
        local.apply_object(hpa_object(target),LAB)
        write_json(directory/'hpa-config.json',hpa_object(target))
        with monitor(directory) as samples:
            def load(name,rate,duration,profile='constant'):
                child=directory/name;child.mkdir()
                phases[name]=dict(at=utc(),monotonic=time.monotonic(),rate=rate,duration=duration,profile=profile)
                write_json(directory/'phases.json',phases)
                result=registration_load(base,child,rate,duration,profile,fresh=False)
                # Fast final responses must not shorten a nominal baseline/high
                # phase (e.g. 1/s ends its last request at second 119 of 120).
                remaining=duration-(time.monotonic()-phases[name]['monotonic'])
                if remaining>0:time.sleep(remaining)
                loads.append(result)
                return result
            # The original 9,450-arrival spike is retained, plus baseline and
            # repeat phases. Worker demand is tested with the sale genuinely open.
            if target=='allocation-worker':
                while api(base,'waiting-room/sale/start',{})['sale_state']!='sale_started': time.sleep(.5)
            load('baseline',1 if target=='allocation-worker' else 2,120)
            load('high',100,180,'spike')
            phases['recovery']=dict(at=utc(),monotonic=time.monotonic(),rate=0,duration=600)
            write_json(directory/'phases.json',phases)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline: time.sleep(min(1,max(0,deadline-time.monotonic())))
            recovery_unresolved=None
            checkpoint=None;extended=None
            if target=='allocation-worker':
                queue=api(base,'waiting-room/queue')['requests']
                write_json(directory/'recovery-queue.json',queue)
                terminal={'RESERVED','UNAVAILABLE','CONFIRMED','CANCELLED','EXPIRED'}
                recovery_unresolved=[p['request_id'] for p in queue if p['status'] not in terminal]
                latest=samples[-1] if samples else {}
                deployment=next((d for d in latest.get('deployments',{}).get('items',[]) if d['metadata']['name']==target),{})
                checkpoint=dict(at=utc(),monotonic=time.monotonic(),unresolved_ids=recovery_unresolved,
                    ready_replicas=deployment.get('status',{}).get('readyReplicas'),backlog=latest.get('backlog'),
                    cpu=hpa_cpu_evidence(samples,target,phases['high']['monotonic'],phases['recovery']['monotonic'],time.monotonic()))
                checkpoint['window_met']=(not recovery_unresolved and checkpoint['ready_replicas']==1 and
                    isinstance(checkpoint['backlog'],dict) and all(checkpoint['backlog'].get(state,0)==0
                        for state in ('QUEUED','IN_PROGRESS','RETRY','BLOCKED')) and checkpoint['cpu']['recovered_below_target'])
                write_json(directory/'ten-minute-checkpoint.json',checkpoint)
                if not checkpoint['window_met']:
                    extended=worker_drain_diagnostic(base,directory,phases,samples)
            load('repeat',100,180,'spike')
            # Allow the final burst's HPA metrics window to be observed.
            time.sleep(30)
        return finalize_hpa(directory,target,base,samples)
    finally:
        # Removing the HPA is cleanup, never counted as observed scale-in.
        k('delete','hpa',target,'--ignore-not-found')


def finalize_hpa(directory,target,base,samples=None):
    """Assess completed raw observations; no traffic or replica mutations."""
    phases=json.loads((directory/'phases.json').read_text())
    if samples is None:samples=json.loads((directory/'timeline.json').read_text())
    loads=[json.loads((directory/name/'summary.json').read_text()) for name in ('baseline','high','repeat')]
    checkpoint=json.loads((directory/'ten-minute-checkpoint.json').read_text()) if target=='allocation-worker' else None
    recovery_unresolved=checkpoint['unresolved_ids'] if checkpoint else None
    extended=json.loads((directory/'extended-drain.json').read_text()) if (directory/'extended-drain.json').exists() else None
    phase_checks={}
    for name,load in zip(('baseline','high','repeat'),loads):
        rows=json.loads((directory/name/'arrivals.json').read_text())
        rate=(1 if target=='allocation-worker' else 2) if name=='baseline' else 100
        duration=120 if name=='baseline' else 180
        profile='constant' if name=='baseline' else 'spike'
        schedule=arrival_schedule(rate,duration,profile)
        lags=[r['launched_seconds']-r['scheduled_seconds'] for r in rows if 'launched_seconds' in r]
        matched=(len(rows)==len(schedule) and all(abs(r['scheduled_seconds']-t)<1e-9 and r['phase']==phase
                    for r,(t,phase) in zip(rows,schedule)))
        check=dict(scheduled=len(schedule),rows=len(rows),launched=len(lags),schedule_matches=matched,
            accepted=sum(r['outcome'].startswith('ACCEPTED') for r in rows),
            http_failures=sum(not 200<=(r.get('response') or {}).get('status',0)<300 for r in rows),
            max_launch_lag_seconds=max(lags) if lags else None)
        check['meets_delivery']=(load['status']=='PASS' and matched and len(lags)==len(schedule)
            and check['accepted']==len(schedule) and check['http_failures']==0 and bool(lags) and max(lags)<=1)
        phase_checks[name]=check
    coverage=(bool(samples) and phases['high']['monotonic']-phases['baseline']['monotonic']>=120
        and phases['recovery']['monotonic']-phases['high']['monotonic']>=180
        and phases['repeat']['monotonic']-phases['recovery']['monotonic']>=600
        and samples[-1]['monotonic']>=phases['repeat']['monotonic']+180)
    transitions=hpa_transitions(samples,target,phases['high']['monotonic'],phases['recovery']['monotonic'],phases['repeat']['monotonic'])
    cpu=hpa_cpu_evidence(samples,target,phases['high']['monotonic'],phases['recovery']['monotonic'],phases['repeat']['monotonic'])
    checks=invariants()
    result=dict(target=target,loads=loads,phase_checks=phase_checks,duration_coverage=coverage,
        transitions=transitions,cpu=cpu,invariants=checks,assessed_at=utc(),
        phases=phases,worker_request_millicores=200 if target=='allocation-worker' else None,
        fixed_api_replicas=4 if target=='allocation-worker' else None,
        status='PASS' if coverage and all(r['meets_delivery'] for r in phase_checks.values()) and all(transitions[key] for key in
            ('baseline_one','scale_out','scale_in','repeat_scale_out')) and cpu['exceeds_target']
            and cpu['recovered_below_target'] and checks['violations']==0 else 'INCONCLUSIVE')
    if target=='allocation-worker':
        backlog=samples[-1].get('backlog',{}) if samples else {}
        result['remaining_backlog']=backlog
        result['demand_interpretation']='Real sale-open allocation jobs; CPU must correlate with backlog. No synthetic CPU burners or manual scaling.'
        # Recovery must actually drain before the repeat spike.
        recovery_samples=[s for s in samples if phases['recovery']['monotonic']<=s['monotonic']<phases['repeat']['monotonic']]
        result['recovery_unresolved_ids']=recovery_unresolved
        last_recovery=recovery_samples[-1] if recovery_samples else {}
        result['recovery_drained']=(recovery_unresolved==[] and 'backlog' in last_recovery and
            all(last_recovery['backlog'].get(state,0)==0 for state in ('QUEUED','IN_PROGRESS','RETRY','BLOCKED')))
        result['ten_minute_checkpoint']=checkpoint
        result['extended_diagnostic']=extended
        result['extended_cycle_status']=result['status'] if extended and extended['drained'] else 'INCONCLUSIVE' if extended else None
        if not result['recovery_drained'] or not checkpoint['window_met']:result['status']='INCONCLUSIVE'
    if checks['violations']:result['status']='FAIL'
    after=capture(base,'TC-24-'+target,'after')
    write_json(directory/'after.json',after)
    final_queue=after['observations']['queue']
    expected=accepted_ids(directory,('baseline','high','repeat'))
    if final_queue['status']==200:
        ids=[p['request_id'] for p in final_queue['data']['requests']]
        result['missing_accepted_ids']=sorted(expected-set(ids))
        result['duplicate_queue_ids']=len(ids)-len(set(ids))
        result['accepted_id_count']=len(expected)
        result['accepted_ids_unique_across_phases']=len(expected)==sum(r['accepted'] for r in phase_checks.values())
        if result['missing_accepted_ids'] or result['duplicate_queue_ids'] or not result['accepted_ids_unique_across_phases']:
            result['status']='FAIL'
            if result.get('extended_cycle_status'):result['extended_cycle_status']='FAIL'
    else:
        result['final_id_verification_error']=final_queue
        if result['status']=='PASS':result['status']='INCONCLUSIVE'
    write_json(directory/'summary.json',result)
    return result


def scale_api(directory,rate=50,duration=30,repeats=3,rates=None,resume=False):
    if not 1<=repeats<=5:raise ValueError('Use 1-5 repeats')
    results=[]
    image_signature=None
    def images(snapshot):
        return {name:sorted({c['imageID'] for pod in snapshot['pods'] if pod['name'].startswith(name+'-')
                            for c in pod['containers']})
                for name in ('waiting-room','frontend','dispatcher-worker','allocation-worker','seat-api','payment-api')}
    for repeat in range(repeats):
      for offered_rate in (rates or [rate]):
        for replicas in ([1,2,4] if repeat%2==0 else [4,2,1]):
            child=directory/f'rate-{offered_rate}-repeat-{repeat+1}-replicas-{replicas}'
            if child.exists():
                if not resume or not (child/'summary.json').exists():
                    raise RuntimeError('Existing incomplete trial is preserved; use a new cohort: '+str(child))
                previous=json.loads((child/'summary.json').read_text())
                if any(previous.get(key)!=value for key,value in dict(rate=offered_rate,duration=duration,replicas=replicas,repeat=repeat+1,profile='constant').items()):
                    raise RuntimeError('Resume conditions differ from the recorded trial')
                signature=images(json.loads((child/'before.json').read_text()))
                if image_signature is not None and signature!=image_signature:raise RuntimeError('Application images differ within cohort')
                image_signature=signature
                results.append(previous)
                continue
            setup_lab(True,'demand-cycle',300,10)
            k('delete','hpa','waiting-room','allocation-worker','--ignore-not-found')
            k('scale','deployment/waiting-room','--replicas='+str(replicas))
            k('rollout','status','deployment/waiting-room','--timeout=180s')
            if not ready_replicas('waiting-room',replicas):
                raise RuntimeError('Requested waiting-room replicas are not all ready')
            child.mkdir()
            with lab_connection() as base:
                write_json(child/'preflight.json',preflight(base))
                before=capture(base,'api-scale','before')
                write_json(child/'before.json',before)
                signature=images(before)
                if image_signature is not None and signature!=image_signature:raise RuntimeError('Application images changed before trial; preserve this cohort')
                image_signature=signature
                with monitor(child) as samples:
                    result=registration_load(base,child,offered_rate,duration,'constant')
                write_json(child/'after.json',capture(base,'api-scale','after'))
            rows=json.loads((child/'arrivals.json').read_text())
            result['served_by_instance']=dict(Counter(r['response'].get('instance') for r in rows if r.get('response',{}).get('instance')))
            result['replicas']=replicas;result['repeat']=repeat+1
            result['distinct_serving_replicas']=len(result['served_by_instance'])
            observed=[];metric_counts=[];hpa_interference=False
            for sample in samples:
                deployment=next((d for d in sample.get('deployments',{}).get('items',[]) if d['metadata']['name']=='waiting-room'),None)
                if deployment:observed.append(deployment.get('status',{}).get('readyReplicas',0))
                hpa_interference|=any(h['spec']['scaleTargetRef']['name']=='waiting-room' for h in sample.get('hpa',{}).get('items',[]))
                pod_names={p['metadata']['name'] for p in sample.get('pods',{}).get('items',[]) if p['metadata'].get('labels',{}).get('app')=='waiting-room'}
                metric_counts.append(sum(p['metadata']['name'] in pod_names for p in sample.get('metrics',{}).get('items',[])))
            result['observed_ready_replicas']=sorted(set(observed))
            result['resource_metrics_cover_all_replicas']=bool(metric_counts) and max(metric_counts)>=replicas
            result['hpa_interference']=hpa_interference
            if (result['distinct_serving_replicas']!=replicas or observed!=[replicas]*len(samples)
                    or not result['resource_metrics_cover_all_replicas'] or hpa_interference) and result['status']=='PASS':
                result['status']='INCONCLUSIVE'
            # Capacity-study SLO, specified before execution. Fixed-load correctness
            # and timing requirements remain unchanged, even above this SLO.
            result['sustainable']=(result['status']=='PASS' and result['http_failed']==0
                and result['p95_ms']<=1000 and result['achieved_registration_rps']>=offered_rate*.95)
            write_json(child/'summary.json',result);results.append(result)
            write_json(directory/'partial-results.json',results)
    result=dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'INCONCLUSIVE',results=results,
        repetitions=repeats, rates=rates or [rate], resumed=resume,application_images=image_signature,
        capacity_slo='P95 <= 1000 ms, achieved >= 95% offered rate, zero HTTP failures, complete delivery within 1s launch lag, correct IDs and SQL, all requested replicas serving.',
        interpretation='Identical offered rate/duration and seed; alternating replica order. '
        'A pass means workload completeness, not a throughput speedup. Port-forward and frontend can be bottlenecks.')
    if any(r['status']=='FAIL' for r in results): result['status']='FAIL'
    write_json(directory/'summary.json',result);return result
