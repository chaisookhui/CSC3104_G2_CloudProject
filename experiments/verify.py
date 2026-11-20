"""Bounded research smoke checks in an initially absent disposable namespace.

Preserves both main and csc3104-lab. Creates/resets/removes only csc3104-check.
Run only after current images are loaded. Not a high-load/statistical experiment.
"""
import sys
import time

import runtime
import run
import workloads


def main():
    target=runtime.local.TEST_NAMESPACE
    if runtime.local.kubectl('get','namespace',target,'--ignore-not-found','-o','name',namespace=None,capture=True):
        raise RuntimeError('Existing csc3104-check found; preserve and inspect it before verification')
    # These process-local bindings keep the public CLI restricted to csc3104-lab.
    runtime.LAB=target; run.LAB=target
    prefix=time.strftime('research-smoke-%Y%m%d-%H%M%S')
    results=[]
    try:
        for scenario,count,ttl in [('F1',8,30),('F7',6,20),('F6',8,120),('F5',8,30)]:
            trace_path=runtime.ROOT/'.local/traces'/f'{prefix}-{scenario}.json'
            trace_path.parent.mkdir(parents=True,exist_ok=True)
            runtime.write_json(trace_path,workloads.make_trace(scenario,count,42,10))
            sys.argv=['run.py','compare','--trace',str(trace_path),'--reset-lab','--hold-ttl',str(ttl),
                      '--timeout','180','--run',prefix+'-'+scenario]
            code=run.main()
            results.append(dict(case=scenario,exit_code=code,run=prefix+'-'+scenario))
            if code: raise RuntimeError(f'{scenario} paired smoke failed; inspect saved evidence')
        runtime.setup_lab(True,hold_ttl=120,batch_size=10)
        with runtime.lab_connection() as base:
            folder=runtime.run_directory(prefix+'-contention')
            result=workloads.contention(base,folder,count=10,workers=10)
            results.append(dict(case='C01',status=result['status'],run=folder.name))
            if result['status']!='PASS': raise RuntimeError('Direct contention smoke failed')
        runtime.setup_lab(True,hold_ttl=120,batch_size=10)
        with runtime.lab_connection() as base:
            folder=runtime.run_directory(prefix+'-register')
            result=workloads.registration_load(base,folder,rate=5,duration=2)
            results.append(dict(case='Q02',status=result['status'],run=folder.name))
            if result['status']!='PASS': raise RuntimeError('Registration calibration failed')
        summary=runtime.run_directory(prefix)
        runtime.write_json(summary/'verification.json',dict(status='PASS',namespace=target,results=results,
            scope='Small integration smoke/calibration only; not full fairness, high-load, scaling, HPA or security acceptance'))
        print('PASS: bounded research smoke checks.',summary,flush=True)
    finally:
        runtime.local.kubectl('delete','namespace',target,'--ignore-not-found','--wait=true','--timeout=180s',namespace=None)
        (runtime.local.LOCAL/f'secrets-{target}.json').unlink(missing_ok=True)


if __name__=='__main__':
    try: main()
    except (RuntimeError,ValueError,OSError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
