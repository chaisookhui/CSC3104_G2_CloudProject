"""Reproduce TC-19/23/24 using the existing lab and acceptance checks.

This command resets ONLY csc3104-lab between independent experiments.
Use a new run ID; interrupted evidence is never overwritten.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import control

from observability import monitor, preflight
from operations import scale_api
from runtime import capture, lab_connection, local, run_directory, setup_lab, utc, write_json
from workloads import contention, registration_load, validate_load


def surge(directory,peaks=None,repeats=3):
    results = []
    control.plan([f'peak-{peak}-repeat-{repeat}' if peaks else f'surge-{repeat}'
                  for peak in (peaks or [100]) for repeat in range(1,repeats+1)]+([] if peaks else ['mixed']))
    for peak in (peaks or [100]):
      for repeat in range(1, repeats+1):
        child = directory/(f'peak-{peak}-repeat-{repeat}' if peaks else f'surge-{repeat}')
        prior=json.loads((child/'summary.json').read_text()) if (child/'summary.json').exists() and (child/'after.json').exists() else None
        with control.unit(child.name,child,prior) as trial:
            if trial.skip:
                results.append(trial.result)
                continue
            child=trial.directory
            setup_lab(True, hold_ttl=300, batch_size=10)
            child.mkdir(exist_ok=True)
            with lab_connection() as base:
                write_json(child/'preflight.json', preflight(base))
                write_json(child/'before.json', capture(base, 'TC-19', 'before'))
                with monitor(child):
                    result = registration_load(base, child, peak, 40, 'spike', True, 600)
                write_json(child/'after.json', capture(base, 'TC-19', 'after'))
            results.append(result)
            write_json(directory/'partial-results.json', results)
            print(f'Surge {peak}/s repeat {repeat}: {result["status"]} {result["outcomes"]}', flush=True)
            trial.complete(result)
    # The follow-up changes only the surge grid. The original mixed trial stays
    # in the default TC-19 workflow and its original evidence is preserved.
    if peaks:
        result=dict(status='FAIL' if any(r['status']=='FAIL' for r in results) else
                    'PASS' if all(r['status']=='PASS' for r in results) else 'INCONCLUSIVE',surge=results)
        write_json(directory/'summary.json',result)
        return result
    child=directory/'mixed'
    prior=json.loads((child/'summary.json').read_text()) if (child/'summary.json').exists() else None
    with control.unit('mixed',child,prior) as trial:
        if trial.skip:
            mixed=trial.result
        else:
            setup_lab(True, hold_ttl=300, batch_size=10)
            child=trial.directory;child.mkdir(exist_ok=True)
            with lab_connection() as base:
                write_json(child/'preflight.json', preflight(base))
                write_json(child/'before.json', capture(base, 'TC-19-mixed', 'before'))
                with monitor(child):
                    mixed = contention(base, child, 40, 32, True)
                write_json(child/'after.json', capture(base, 'TC-19-mixed', 'after'))
            trial.complete(mixed)
    result = dict(status='PASS' if all(r['status']=='PASS' for r in results+[mixed]) else 'INCONCLUSIVE',
                  surge=results, mixed=mixed)
    if any(r['status']=='FAIL' for r in results+[mixed]): result['status']='FAIL'
    write_json(directory/'summary.json', result)
    return result


@control.controlled_main
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['19', '23', 'capacity', '24-api', '24-worker'], required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--reset-lab', action='store_true',help='Required for every study that deploys or resets the lab')
    parser.add_argument('--resume',action='store_true',help='Verify and reuse completed units; retry interrupted units in fresh attempt directories')
    parser.add_argument('--finalize-recorded',action='store_true',help='Assess a completed HPA timeline after a reporting error; generates no load')
    parser.add_argument('--rates',type=int,nargs='+',help='Explicit capacity grid; default remains 20/40/60/80/100')
    parser.add_argument('--allow-high-rate-lab',action='store_true',help='Explicit lab-only opt-in to 201-300 requests/s; all other limits and SLOs unchanged')
    parser.add_argument('--replicas',type=int,nargs='+',choices=[1,2,4],help='Fixed API replica subset for capacity trials')
    parser.add_argument('--repeats',type=int,help='1-5 trials per point; defaults unchanged')
    parser.add_argument('--peaks',type=int,nargs='+',choices=[100,150,200],help='TC-19 follow-up peak grid; unchanged 10/20/10 seconds and 600s admission deadline')
    args = parser.parse_args()
    if (args.rates or args.replicas or args.allow_high_rate_lab) and args.case!='capacity':
        parser.error('--rates, --replicas and --allow-high-rate-lab apply only to capacity')
    if args.peaks and args.case!='19':parser.error('--peaks applies only to case 19')
    if args.repeats is not None and (args.case not in ('19','23','capacity') or not 1<=args.repeats<=5):
        parser.error('--repeats requires case 19/23/capacity and 1-5')
    if args.rates:
        if len(set(args.rates))!=len(args.rates):parser.error('Duplicate rates')
        for rate in args.rates:validate_load(rate,30,args.allow_high_rate_lab)
    if not args.finalize_recorded and not args.reset_lab:
        parser.error('--reset-lab is required for a new or resumed deployed study')
    directory = run_directory(args.run)
    manifest=directory/'run.json'
    if args.resume:
        if manifest.exists():
            recorded=json.loads(manifest.read_text())['arguments']
            for key,value in vars(args).items():
                if key not in ('resume','run') and recorded.get(key,False if isinstance(value,bool) else None)!=value:
                    raise ValueError('Resume conditions differ: '+key)
    elif any(p.name!='.control' for p in directory.iterdir()):
        raise ValueError('Choose a new run ID, or --resume; existing evidence is preserved')
    if not manifest.exists():
        write_json(manifest, dict(arguments=vars(args), started_at=utc()))
    completed=directory/'summary.json'
    if args.resume and completed.exists() and not control.session().data['units']:
        previous=json.loads(completed.read_text())
        control.session().adopt('legacy-completed-study',directory,previous)
        return 0 if previous['status']=='PASS' else 2
    try:
        from loadgen import check_runtime
        check_runtime()
        local.preflight()
        if args.finalize_recorded:
            from operations import finalize_hpa
            with lab_connection() as base:
                result=finalize_hpa(directory,'waiting-room' if args.case=='24-api' else 'allocation-worker',base)
        elif args.case=='19': result=surge(directory,args.peaks,args.repeats or 3)
        elif args.case in ('23', 'capacity'):
            result=scale_api(directory, 50, 30, args.repeats or (3 if args.case=='23' else 1),
                             (args.rates or [20,40,60,80,100]) if args.case=='capacity' else None,args.resume,
                             allow_high_rate_lab=args.allow_high_rate_lab,replica_counts=args.replicas)
        else:
            from operations import hpa_trial
            control.plan(['hpa-cycle'])
            with control.unit('hpa-cycle',directory/'hpa-cycle') as trial:
                if trial.skip:result=trial.result
                else:
                    result=hpa_trial(trial.directory, 'waiting-room' if args.case=='24-api' else 'allocation-worker')
                    trial.complete(result)
            write_json(directory/'summary.json',result)
        write_json(directory/'execution.json',dict(arguments=vars(args),finished_at=utc(),
                   status=result['status'],exit_code=0 if result['status']=='PASS' else 2))
        print(json.dumps(result, indent=2), flush=True)
        return 0 if result['status']=='PASS' else 2
    except control.Pause:
        raise
    except BaseException as error:
        write_json(directory/'interrupted.json', dict(at=utc(), error=type(error).__name__, message=str(error)))
        raise


if __name__=='__main__':
    sys.exit(main())
