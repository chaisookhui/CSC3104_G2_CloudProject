"""Run and record experiments only in csc3104-lab. Registration requires aiohttp."""
import argparse
import json
from pathlib import Path
import sys
import time
from fairness import paired_analysis, write_report
from resilience import crash_or_lost_reply, outage, lifecycle_race
from operations import autoscale, scale_api
from gateway_check import gateway_check
from observability import collect_logs

from runtime import (LAB, capture, invariants, k, lab_connection, local,
                     run_directory, setup_lab, utc, write_json)
from workloads import (contention, digest, make_trace, registration_load, replay,
                       validate_trace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    lab = sub.add_parser('lab', help='Create/update the lab; --reset-lab explicitly erases only lab data')
    lab.add_argument('--reset-lab', action='store_true')
    lab.add_argument('--policy', choices=['demand-cycle','fcfs'], default='demand-cycle')
    lab.add_argument('--hold-ttl', type=int, default=300)
    lab.add_argument('--batch-size', type=int, default=10)
    trace = sub.add_parser('trace', help='Save a seeded workload without contacting Docker')
    trace.add_argument('--scenario', choices=[f'F{i}' for i in range(1,8)], default='F1')
    trace.add_argument('--count', type=int, default=40); trace.add_argument('--seed', type=int, default=42)
    trace.add_argument('--batch-size', type=int, default=10); trace.add_argument('--output', type=Path, required=True)
    snap = sub.add_parser('capture'); snap.add_argument('--case', default='manual'); snap.add_argument('--phase', default='snapshot')
    check = sub.add_parser('invariants')
    load = sub.add_parser('register'); load.add_argument('--rate',type=int,default=5); load.add_argument('--duration',type=int,default=10)
    load.add_argument('--profile',choices=['constant','spike'],default='constant')
    load.add_argument('--admit',action='store_true',help='Open sale and verify stable positions and complete admission')
    load.add_argument('--timeout',type=int,default=600)
    compete = sub.add_parser('contention'); compete.add_argument('--count',type=int,default=10); compete.add_argument('--workers',type=int,default=10)
    compete.add_argument('--mixed',action='store_true',help='Compete using sizes 1,2,3,4')
    journey = sub.add_parser('replay'); journey.add_argument('--trace',type=Path,required=True); journey.add_argument('--timeout',type=int,default=420)
    pair = sub.add_parser('compare'); pair.add_argument('--trace',type=Path,required=True)
    pair.add_argument('--reset-lab',action='store_true',help='Required: erase only lab state before EACH policy')
    pair.add_argument('--hold-ttl',type=int,default=30); pair.add_argument('--replicas',type=int,default=1)
    pair.add_argument('--repeats',type=int,default=1); pair.add_argument('--timeout',type=int,default=420)
    pair.add_argument('--seeds',type=int,default=1,help='Independent consecutive trace seeds; each policy receives the same trace')
    fault=sub.add_parser('fault',help='Inject faults only into the isolated lab; restores resources in finally')
    fault.add_argument('--scenario',choices=['lost-reply','worker-crash','redis','postgres','both'],required=True)
    fault.add_argument('--seconds',type=int,default=30)
    race=sub.add_parser('race',help='Race payment and cancellation, optionally at hold expiry')
    race.add_argument('--near-expiry',action='store_true')
    gateway=sub.add_parser('gateway',help='Test real cookie ownership and administrator access through the lab gateway')
    scaling=sub.add_parser('scale-api',help='Paired 1/2/4 waiting-room API experiments, resetting only lab per trial')
    scaling.add_argument('--reset-lab',action='store_true',required=True)
    scaling.add_argument('--rate',type=int,default=50);scaling.add_argument('--duration',type=int,default=30)
    scaling.add_argument('--repeats',type=int,default=3)
    scaling.add_argument('--capacity',action='store_true',help='Additional 20/40/60/80/100 requests/s capacity grid; no change to fixed-load default')
    auto=sub.add_parser('autoscale',help='Configure or remove optional lab HPAs; metrics must be available')
    auto.add_argument('--install-metrics',action='store_true',help='Install pinned metrics-server into private Kind, with local kubelet TLS exception')
    auto.add_argument('--disable',action='store_true')
    for command in (snap,check,load,compete,journey,pair,fault,race,scaling,auto,gateway): command.add_argument('--run')
    args = parser.parse_args()
    if args.command in ('register','scale-api'):
        from loadgen import check_runtime
        check_runtime()
    if args.command == 'trace':
        data = make_trace(args.scenario,args.count,args.seed,args.batch_size); validate_trace(data)
        args.output.parent.mkdir(parents=True,exist_ok=True); write_json(args.output,data)
        print(f'Saved {len(data["customers"])} customers: {args.output} SHA256={digest(data)}'); return 0
    local.preflight()
    if args.command == 'lab':
        setup_lab(args.reset_lab,args.policy,args.hold_ttl,args.batch_size)
        print('Lab ready. Open http://127.0.0.1:18100 using the documented port-forward; follow output/pdf/GROUP02_INSTRUCTIONS.pdf.'); return 0
    directory = run_directory(args.run)
    if any(directory.iterdir()):
        # Capture supports appending phases to a run; workload results must not overwrite earlier evidence.
        if args.command not in ('capture','invariants'):
            raise RuntimeError('Run directory already has evidence. Choose a new --run ID.')
    manifest_path=directory/'run.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else dict(namespace=LAB,started_at=utc(),commands=[])
    manifest['commands'].append(dict(arguments=vars(args),at=utc()))
    write_json(manifest_path,manifest)
    try:
        if args.command=='autoscale':
            result=autoscale(directory,args.install_metrics,args.disable);print(json.dumps(result,indent=2));return 0
        if args.command=='scale-api':
            result=scale_api(directory,args.rate,args.duration,args.repeats,[20,40,60,80,100] if args.capacity else None);print(json.dumps(result,indent=2));return 0 if result['status']=='PASS' else 2
        if args.command == 'compare':
            if not args.reset_lab:
                raise ValueError('compare requires --reset-lab: it erases only lab data before each policy')
            if not 1 <= args.replicas <= 8 or not 1 <= args.repeats <= 10:
                raise ValueError('Use 1-8 allocation workers and 1-10 repeats')
            trace_data = validate_trace(json.loads(args.trace.read_text(encoding='utf-8')))
            if not 1<=args.seeds<=30: raise ValueError('Use 1-30 seeds')
            if args.seeds>1 and make_trace(trace_data['scenario'],len(trace_data['customers']),trace_data['seed'],trace_data['batch_size'])!=trace_data:
                raise ValueError('Multiple seeds require an unmodified generated trace')
            write_json(directory/'trace.json',trace_data)
            results=[]
            original_trace=trace_data
            for trial in range(args.repeats*args.seeds):
                repeat=trial%args.repeats
                seed=original_trace['seed']+trial//args.repeats
                trace_data=original_trace if args.seeds==1 else make_trace(original_trace['scenario'],len(original_trace['customers']),seed,original_trace['batch_size'])
                policies = ['demand-cycle','fcfs'] if trial%2==0 else ['fcfs','demand-cycle']
                for policy in policies:
                    print(f'Repeat {repeat+1}/{args.repeats}, {policy}: resetting only {LAB}',flush=True)
                    setup_lab(True,policy,args.hold_ttl,trace_data['batch_size'])
                    k('scale','deployment/allocation-worker',f'--replicas={args.replicas}')
                    k('rollout','status','deployment/allocation-worker','--timeout=180s')
                    child=directory/f'seed-{seed}-repeat-{repeat+1}-{policy}'; child.mkdir()
                    with lab_connection() as base:
                        write_json(child/'before.json',capture(base,'F01','before'))
                        result=replay(base,trace_data,child,args.timeout)
                        write_json(child/'after.json',capture(base,'F01','after'))
                    collect_logs(child)
                    results.append(dict(seed=seed,repeat=repeat+1,policy=policy,result=result))
            matching=len({entry['result']['initial_fingerprint'] for entry in results})==1
            status='PASS' if matching and all(entry['result']['status']=='PASS' for entry in results) else 'INCONCLUSIVE'
            if any(entry['result']['status']=='FAIL' for entry in results): status='FAIL'
            write_json(directory/'comparison.json',dict(namespace=LAB,status=status, identical_initial_inventory=matching,
                trace_sha256=digest(original_trace),results=results, fairness=paired_analysis(results),
                interpretation='PASS means comparable executions and safety, not Demand-Cycle superiority or statistical significance.'))
            write_report(directory,results)
            print(f'{status}: paired comparison saved in {directory}'); return 0 if status=='PASS' else 2
        with lab_connection() as base:
            if args.command == 'capture':
                safe=''.join(c for c in args.phase if c.isalnum() or c in '-_') or 'snapshot'
                path=directory/(time.strftime('%Y%m%d-%H%M%S')+f'-{time.time_ns()}-'+safe+'.json')
                write_json(path,capture(base,args.case,args.phase)); print(path); return 0
            if args.command == 'invariants':
                result=invariants(); write_json(directory/f'invariants-{time.time_ns()}.json',result)
            else:
                write_json(directory/'before.json',capture(base,args.command,'before'))
                if args.command=='register': result=registration_load(base,directory,args.rate,args.duration,args.profile,args.admit,args.timeout)
                elif args.command=='contention': result=contention(base,directory,args.count,args.workers,args.mixed)
                elif args.command=='fault':
                    result=crash_or_lost_reply(base,directory,args.scenario=='worker-crash') if args.scenario in ('lost-reply','worker-crash') else outage(base,directory,args.scenario,args.seconds)
                elif args.command=='race': result=lifecycle_race(base,directory,args.near_expiry)
                elif args.command=='gateway':result=gateway_check(base,directory)
                else: result=replay(base,validate_trace(json.loads(args.trace.read_text(encoding='utf-8'))),directory,args.timeout)
                write_json(directory/'after.json',capture(base,args.command,'after'))
            collect_logs(directory)
            print(json.dumps(result,indent=2,default=str))
            print('Evidence:',directory)
            return 0 if result['status']=='PASS' else 2
    except BaseException as error:
        write_json(directory/'interrupted.json',dict(at=utc(),error=type(error).__name__,message=str(error)))
        raise


if __name__=='__main__':
    try:
        sys.exit(main())
    except (ValueError,RuntimeError,OSError,KeyError) as error:
        print('Experiment stopped: '+str(error),file=sys.stderr); sys.exit(1)
