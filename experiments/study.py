"""Reproduce TC-19/23/24 using the existing lab and acceptance checks.

This command resets ONLY csc3104-lab between independent experiments.
Use a new run ID; interrupted evidence is never overwritten.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from observability import monitor, preflight
from operations import scale_api
from runtime import capture, lab_connection, local, run_directory, setup_lab, utc, write_json
from workloads import contention, registration_load


def surge(directory):
    results = []
    for repeat in range(1, 4):
        setup_lab(True, hold_ttl=300, batch_size=10)
        child = directory/f'surge-{repeat}'
        child.mkdir()
        with lab_connection() as base:
            write_json(child/'preflight.json', preflight(base))
            write_json(child/'before.json', capture(base, 'TC-19', 'before'))
            with monitor(child):
                result = registration_load(base, child, 100, 40, 'spike', True, 600)
            write_json(child/'after.json', capture(base, 'TC-19', 'after'))
        results.append(result)
        write_json(directory/'partial-results.json', results)
        print(f'Surge {repeat}: {result["status"]} {result["outcomes"]}', flush=True)
    setup_lab(True, hold_ttl=300, batch_size=10)
    child = directory/'mixed';child.mkdir()
    with lab_connection() as base:
        write_json(child/'preflight.json', preflight(base))
        write_json(child/'before.json', capture(base, 'TC-19-mixed', 'before'))
        with monitor(child):
            mixed = contention(base, child, 40, 32, True)
        write_json(child/'after.json', capture(base, 'TC-19-mixed', 'after'))
    result = dict(status='PASS' if all(r['status']=='PASS' for r in results+[mixed]) else 'INCONCLUSIVE',
                  surge=results, mixed=mixed)
    if any(r['status']=='FAIL' for r in results+[mixed]): result['status']='FAIL'
    write_json(directory/'summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['19', '23', 'capacity', '24-api', '24-worker'], required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--reset-lab', action='store_true',help='Required for every study that deploys or resets the lab')
    parser.add_argument('--resume',action='store_true',help='Resume only unstarted replica/capacity trials; all prior results, including failures, are retained')
    parser.add_argument('--finalize-recorded',action='store_true',help='Assess a completed HPA timeline after a reporting error; generates no load')
    args = parser.parse_args()
    if not args.finalize_recorded and not args.reset_lab:
        parser.error('--reset-lab is required for a new or resumed deployed study')
    directory = run_directory(args.run)
    if args.finalize_recorded:
        if args.case not in ('24-api','24-worker') or (directory/'summary.json').exists() or not (directory/'interrupted.json').exists():
            raise ValueError('Finalization requires a completed HPA record with a reporting interruption and no final summary')
        write_json(directory/('finalization-'+str(time.time_ns())+'.json'),dict(arguments=vars(args),at=utc()))
    elif args.resume:
        if args.case not in ('23','capacity') or (directory/'summary.json').exists():raise ValueError('Only an incomplete replica/capacity cohort can resume')
        previous=json.loads((directory/'run.json').read_text())
        if previous['arguments']['case']!=args.case:raise ValueError('Resume case differs from original command')
        write_json(directory/('resume-'+str(time.time_ns())+'.json'),dict(arguments=vars(args),started_at=utc()))
    else:
        if any(directory.iterdir()): raise ValueError('Choose a new run ID; existing evidence is preserved')
        write_json(directory/'run.json', dict(arguments=vars(args), started_at=utc()))
    try:
        from loadgen import check_runtime
        check_runtime()
        local.preflight()
        if args.finalize_recorded:
            from operations import finalize_hpa
            with lab_connection() as base:
                result=finalize_hpa(directory,'waiting-room' if args.case=='24-api' else 'allocation-worker',base)
        elif args.case=='19': result=surge(directory)
        elif args.case in ('23', 'capacity'):
            result=scale_api(directory, 50, 30, 3 if args.case=='23' else 1,
                             [20,40,60,80,100] if args.case=='capacity' else None,args.resume)
        else:
            from operations import hpa_trial
            result=hpa_trial(directory, 'waiting-room' if args.case=='24-api' else 'allocation-worker')
        write_json(directory/'execution.json',dict(arguments=vars(args),finished_at=utc(),
                   status=result['status'],exit_code=0 if result['status']=='PASS' else 2))
        print(json.dumps(result, indent=2), flush=True)
        return 0 if result['status']=='PASS' else 2
    except BaseException as error:
        write_json(directory/'interrupted.json', dict(at=utc(), error=type(error).__name__, message=str(error)))
        raise


if __name__=='__main__':
    sys.exit(main())
