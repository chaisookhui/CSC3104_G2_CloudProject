"""Run existing SQL integration suites in a dedicated *_test DB in the lab.

Resets only csc3104-lab. Credentials stay in the child environment, never logs.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from urllib.parse import quote

from runtime import LAB, k, local, run_directory, setup_lab, utc, write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--reset-lab',action='store_true',required=True)
    args=parser.parse_args()
    directory=run_directory(args.run)
    if any(directory.iterdir()):raise ValueError('Choose a new run ID')
    setup_lab(True,hold_ttl=300,batch_size=10)
    k('exec','postgres-0','--','psql','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1',
      '-c','CREATE DATABASE tc_regression_test;')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    command=[str(local.kubectl_binary()),'--kubeconfig',str(local.KUBECONFIG),'--context',local.CONTEXT,
             '--namespace',LAB,'port-forward','--address','127.0.0.1','service/postgres',str(port)+':5432']
    results=[]
    with (directory/'port-forward.log').open('w',encoding='utf-8') as log:
      process=subprocess.Popen(command,stdout=log,stderr=log,stdin=subprocess.DEVNULL)
      try:
        deadline=time.monotonic()+30
        while True:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=1):break
            except OSError:
                if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('PostgreSQL port-forward unavailable')
                time.sleep(.2)
        credentials=json.loads((local.LOCAL/('secrets-'+LAB+'.json')).read_text())
        dsn='postgresql://postgres:'+quote(credentials['POSTGRES_PASSWORD'],safe='')+'@127.0.0.1:'+str(port)+'/tc_regression_test'
        environment={**os.environ,'TEST_DATABASE_URL':dsn,'PAYMENT_TEST_DATABASE_URL':dsn,'DISPATCHER_TEST_DATABASE_URL':dsn}
        for name,path in [('seat-store','src/seat-store/tests'),('payment','src/waitlist-payment/tests'),('dispatcher','src/batch-dispatcher/tests'),('booking','tests/test_booking_integration.py')]:
            with (directory/(name+'.log')).open('w',encoding='utf-8') as output:
                code=subprocess.call([sys.executable,'-m','pytest',path,'-q','--tb=short'],env=environment,stdout=output,stderr=subprocess.STDOUT)
            results.append(dict(suite=name,exit_code=code,finished_at=utc()))
            write_json(directory/'partial-results.json',results)
        result=dict(status='PASS' if all(r['exit_code']==0 for r in results) else 'FAIL',results=results,
                    namespace=LAB,database='tc_regression_test',finished_at=utc())
        write_json(directory/'summary.json',result)
        return 0 if result['status']=='PASS' else 1
      finally:
        process.terminate()
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':sys.exit(main())
