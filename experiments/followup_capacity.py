"""Finish unrun capacity points and boundary repetitions, retaining interrupted cohorts.

Run only after the preceding deployed study process has exited. Every point uses
the existing study.py runner and a fresh independent csc3104-lab reset.
"""
import argparse
import json
import subprocess
import sys
import control

from followup import boundary_trials
from runtime import RESULTS, ROOT, run_directory, utc, write_json


@control.controlled_main(deployed=False)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior',required=True,help='Retained incomplete 200/250/300 cohort')
    parser.add_argument('--run',required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    directory=run_directory(args.run)
    if not args.resume and any(p.name!='.control' for p in directory.iterdir()):raise ValueError('Use a fresh completion run ID or --resume')
    prior=RESULTS/args.prior
    points=json.loads((prior/'partial-results.json').read_text())
    if not (directory/'run.json').exists():write_json(directory/'run.json',dict(arguments=vars(args),at=utc(),prior=str(prior),scope=__doc__))
    attempts=json.loads((directory/'attempts.json').read_text()) if (directory/'attempts.json').exists() else []
    def execute(name,arguments):
        run=args.run+'-'+name
        child=RESULTS/run

        command=[sys.executable,'experiments/study.py',*arguments,'--run',run]
        if child.exists() and any(child.iterdir()):command.append('--resume')
        record=dict(run=run,command=command,started_at=utc())
        write_json(directory/(name+'-command.json'),record)
        with (directory/(name+'.log')).open('a',encoding='utf-8') as log:
            record['exit_code']=control.child_call(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        summary=child/'summary.json'
        result=json.loads(summary.read_text()) if summary.exists() else None
        if result is None:raise RuntimeError('Child stopped without a completed result; no next unit started: '+run)
        record.update(status=result['status'],finished_at=utc())
        attempts.append(record);write_json(directory/'attempts.json',attempts)
        print(run,record['status'],flush=True)
        return result
    # Separate 300/s processes prevent a post-load observation failure at one
    # replica count from silently leaving the other configurations unattempted.
    for replicas in (1,2,4):
        result=execute(f'300-n{replicas}',['--case','capacity','--reset-lab','--rates','300',
            '--replicas',str(replicas),'--repeats','1','--allow-high-rate-lab'])
        if result:points.extend(result['results'])
        write_json(directory/'initial-points.json',points)
    for name,command in boundary_trials(points):
        # boundary_trials supplies the script name; execute adds it once.
        execute(name,command[1:])
    write_json(directory/'summary.json',dict(status='PASS' if all(a['status']=='PASS' for a in attempts) else 'INCONCLUSIVE',
        finished_at=utc(),attempts=attempts,initial_points=points,
        interpretation='Statuses retain workload/observation outcomes. Individual sustainable flags retain the unchanged capacity SLO; no interrupted result is overwritten.'))
    return 0


if __name__=='__main__':raise SystemExit(main())
