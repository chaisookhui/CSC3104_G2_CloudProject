"""Deployed regressions for the seven previously passing cases.

Uses original workloads and repetitions: TC14/15/16/20 three times and TC18 ten
independent seeds. --bounded is an explicitly limited diagnostic.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from runtime import local, run_directory, utc, write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--reset-lab',action='store_true',required=True)
    coverage=parser.add_mutually_exclusive_group()
    coverage.add_argument('--full-coverage',action='store_true',default=True,
        help='TC16:3 repeats per1/2/4 workers; TC18:10 independent F1 seeds42-51, both policies')
    coverage.add_argument('--bounded',action='store_false',dest='full_coverage',
        help='One repeat per variant and only seed42; does not recertify historical repetitions')
    args=parser.parse_args()
    directory=run_directory(args.run)
    if any(directory.iterdir()):raise ValueError('Choose a new run ID')
    results=[]
    def command(case,arguments,reset=True,ttl=300):
        name=args.run+'-'+case
        if reset:
            with (directory/(case+'-reset.log')).open('w',encoding='utf-8') as log:
                code=subprocess.call([sys.executable,'experiments/run.py','lab','--reset-lab','--hold-ttl',str(ttl),'--batch-size','10'],stdout=log,stderr=subprocess.STDOUT)
            if code:raise RuntimeError(case+' lab reset failed')
        with (directory/(case+'.log')).open('w',encoding='utf-8') as log:
            code=subprocess.call([sys.executable,'experiments/run.py',*arguments,'--run',name],stdout=log,stderr=subprocess.STDOUT)
        record=dict(case=case,arguments=arguments,run=name,exit_code=code,finished_at=utc())
        path=directory.parent/name
        summary=path/('comparison.json' if arguments[0]=='compare' else 'summary.json')
        record['status']=json.loads(summary.read_text())['status'] if summary.exists() else 'BLOCKED'
        results.append(record);write_json(directory/'partial-results.json',results)
        print(case,record['status'],flush=True)
    repeats=range(1,4) if args.full_coverage else range(1,2)
    def label(case,repeat):return case+('-r'+str(repeat) if args.full_coverage else '')
    for repeat in repeats:
        command(label('TC14',repeat),['contention','--count','1','--workers','1'])
    for repeat in repeats:
        command(label('TC15',repeat),['register','--rate','5','--duration','10'])
    trace=directory/'F1-42.json'
    subprocess.run([sys.executable,'experiments/run.py','trace','--scenario','F1','--count','40','--seed','42','--batch-size','10','--output',str(trace)],check=True)
    for n in (1,2,4):
        command('TC16-'+str(n),['compare','--trace',str(trace),'--reset-lab','--hold-ttl','120','--replicas',str(n),'--repeats','3' if args.full_coverage else '1'],False)
    # TC-18's F1 seed-42 correctness is the same pair as the one-worker TC-16
    # trial. Do not misrepresent this as a fresh ten-seed fairness re-evaluation.
    if args.full_coverage:
        command('TC18',['compare','--trace',str(trace),'--reset-lab','--hold-ttl','120',
            '--replicas','1','--repeats','1','--seeds','10'],False)
    else:
        results.append(dict(case='TC18-bounded',status=next(r['status'] for r in results if r['case']=='TC16-1'),
                            reused_run=args.run+'-TC16-1',scope='F1, 40 parties, seed42, both policies. The historical ten-seed study is not repeated.'))
    for repeat in repeats:
        command(label('TC20-active',repeat),['race'])
    for repeat in repeats:
        command(label('TC20-expiry',repeat),['race','--near-expiry'],ttl=20)
    command('TC21-reply',['fault','--scenario','lost-reply'])
    command('TC21-crash',['fault','--scenario','worker-crash'])
    for dependency in ('redis','postgres','both'):
        command('TC22-'+dependency,['fault','--scenario',dependency,'--seconds','60'])
    result=dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'INCONCLUSIVE',
        scope=__doc__,full_coverage=args.full_coverage,results=results,finished_at=utc())
    if any(r['status']=='FAIL' for r in results):result['status']='FAIL'
    write_json(directory/'summary.json',result)
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':sys.exit(main())
