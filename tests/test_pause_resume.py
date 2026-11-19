"""Local-only pause/resume tests. No Docker, Kubernetes or deployed workloads."""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
import control
import runtime
import study
import run


class PauseResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.environment=patch.dict('os.environ',{},clear=False)
        self.environment.start()
        os.environ.pop('CSC3104_CONTROL',None)
        os.environ.pop('CSC3104_CONTROL_ACK',None)
        self.results=patch.object(control,'RESULTS',self.root/'results')
        self.results.start()

    def tearDown(self):
        self.results.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def session(self,resume=False,**kwargs):
        return control.Session(self.root/'cohort', ['unchanged protocol'], resume,
                               identity={'source':'original'}, deployed=False, **kwargs)

    def request(self,session,mode):
        control.atomic_json(session.request_path,dict(id=str(time.time_ns()),mode=mode))

    def test_safe_pair_commits_both_policies_and_starts_no_next_pair(self):
        session=self.session(); executed=[]
        with self.assertRaises(control.Pause),session.activate():
            for seed in (42,43):
                with control.unit(str(seed),self.root/str(seed)) as unit:
                    for policy in ('demand-cycle','fcfs'):
                        executed.append((seed,policy))
                        if policy=='demand-cycle':self.request(session,'safe')
                        control.sleep(.01)  # safe does not interrupt any phase
                    (unit.directory/'evidence.txt').write_text('both policies')
                    unit.complete({'status':'PASS'})
        ledger=control.read(session.path)
        self.assertEqual(executed,[(42,'demand-cycle'),(42,'fcfs')])
        self.assertEqual(ledger['state'],'PAUSED')
        self.assertEqual(ledger['units']['42']['state'],'COMPLETE')
        self.assertNotIn('43',ledger['units'])
        resumed=self.session(True)
        with resumed.activate():
            with control.unit('42',self.root/'42') as unit:
                self.assertTrue(unit.skip)
                self.assertEqual(unit.result,{'status':'PASS'})
            with control.unit('43',self.root/'43') as unit:
                self.assertFalse(unit.skip)
                unit.complete({'status':'FAIL'})

    def test_immediate_retains_complete_failure_and_only_interrupts_current_unit(self):
        session=self.session()
        with self.assertRaises(control.Pause),session.activate():
            with control.unit('complete',self.root/'done') as unit:
                (unit.directory/'raw').write_text('valid failed trial')
                unit.complete({'status':'INCONCLUSIVE'})
            with control.unit('active',self.root/'active') as unit:
                (unit.directory/'raw').write_text('partial evidence')
                self.request(session,'immediate')
                control.sleep(60)
            self.fail('Must not advance')
        ledger=control.read(session.path)
        self.assertEqual({k:v['state'] for k,v in ledger['units'].items()},
                         {'complete':'COMPLETE','active':'INTERRUPTED'})
        original=(self.root/'active/raw').read_bytes()
        resumed=self.session(True)
        with resumed.activate():
            with control.unit('complete',self.root/'done') as unit:
                self.assertTrue(unit.skip)
            with control.unit('active',self.root/'active') as unit:
                self.assertNotEqual(unit.directory,self.root/'active')
                unit.complete({'status':'PASS'})
        self.assertEqual((self.root/'active/raw').read_bytes(),original)
        self.assertEqual([a['state'] for a in resumed.data['units']['active']['attempts']],
                         ['INTERRUPTED','COMPLETE'])

    def test_stale_running_attempt_is_retried_without_overwriting(self):
        session=self.session()
        session.data['units']['active']=dict(state='RUNNING',directory=str(self.root/'active'),
            attempts=[dict(state='RUNNING',directory=str(self.root/'active'))])
        (self.root/'active').mkdir();(self.root/'active/raw').write_text('crash evidence')
        session.save()
        resumed=self.session(True)
        self.assertEqual(resumed.data['units']['active']['state'],'INTERRUPTED')
        with resumed.activate():
            with control.unit('active',self.root/'active') as unit:
                self.assertNotEqual(unit.directory,self.root/'active')
                unit.complete({'status':'PASS'})
        self.assertEqual((self.root/'active/raw').read_text(),'crash evidence')

    def test_configuration_source_and_completed_evidence_changes_are_refused(self):
        session=self.session()
        with session.activate():
            with control.unit('one',self.root/'one') as unit:
                (unit.directory/'raw').write_text('original')
                unit.complete({'status':'PASS'})
        with self.assertRaisesRegex(RuntimeError,'configuration'):
            control.Session(session.directory,['different'],True,False,identity={'source':'original'})
        with self.assertRaisesRegex(RuntimeError,'source'):
            control.Session(session.directory,['unchanged protocol'],True,False,identity={'source':'changed'})
        (self.root/'one/raw').write_text('tampered')
        with self.assertRaisesRegex(RuntimeError,'evidence changed'):
            self.session(True)

    def test_image_config_drift_blocks_before_unit_body_or_lab_reset(self):
        session=control.Session(self.root/'cohort',[],deployed=True,identity={},live=lambda:{'image':'original'})
        with session.activate():
            with control.unit('one',self.root/'one') as unit:unit.complete({'status':'PASS'})
        resumed=control.Session(session.directory,[],True,True,identity={},live=lambda:{'image':'different'})
        with resumed.activate():
            with self.assertRaisesRegex(RuntimeError,'image/configuration'):
                with control.unit('two',self.root/'two'):
                    self.fail('Must refuse before mutations')
        self.assertNotIn('two',resumed.data['units'])

    def test_live_runner_lock_prevents_another_process(self):
        lock=control.RESULTS/'.runner.lock';lock.parent.mkdir(parents=True)
        import os
        control.atomic_json(lock,dict(pid=os.getpid(),run='another'))
        session=control.Session(self.root/'cohort',[],identity={},live=lambda:{})
        with self.assertRaisesRegex(RuntimeError,'Another deployed runner'):
            with session.activate():self.fail('Lock not enforced')
        self.assertTrue(lock.exists())

    def test_cleanup_runs_despite_pending_immediate_request(self):
        session=self.session()
        with session.activate():
            self.request(session,'immediate')
            with control.cleanup():control.sleep(.06)
            with self.assertRaises(control.Pause):control.immediate()

    def test_child_pause_exit_prevents_parent_advancing(self):
        session=self.session()
        with self.assertRaises(control.Pause),session.activate():
            control.child_call([sys.executable,'-c','raise SystemExit(75)'])
            self.fail('Parent advanced after child pause')

    def test_inherited_pause_signal_reaches_real_child_before_parent_returns(self):
        session=self.session();marker=self.root/'child-started';child=self.root/'child'
        script="""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import control
session=control.Session(Path(sys.argv[2]),[],deployed=False,identity={})
try:
    with session.activate():
        for key in ('first','second'):
            with control.unit(key,session.directory/key) as unit:
                Path(sys.argv[3]).write_text(key)
                control.sleep(.3)
                (unit.directory/'raw').write_text('saved child evidence')
                unit.complete({'status':'PASS'})
except control.Pause:
    raise SystemExit(75)
"""
        def pause():
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
            self.request(session,'safe')
        with self.assertRaises(control.Pause),session.activate():
            thread=threading.Thread(target=pause);thread.start()
            try:
                control.child_call([sys.executable,'-c',script,str(Path(control.__file__).parent),str(child),str(marker)])
            finally:thread.join()
        self.assertEqual(marker.read_text(),'first')
        ledger=control.read(child/'.control/ledger.json')
        self.assertEqual(ledger['state'],'PAUSED')
        self.assertEqual(ledger['units']['first']['state'],'COMPLETE')
        self.assertFalse((child/'second').exists())

    def test_legacy_completed_failure_is_imported_without_running_or_rewriting_it(self):
        child=self.root/'legacy';child.mkdir()
        control.atomic_json(child/'before.json',dict(source_files_sha256={'src/service.py':'unchanged'},
            pods=[dict(containers=[dict(imageID='sha256:original')])]))
        control.atomic_json(child/'summary.json',dict(status='FAIL'))
        original=(child/'summary.json').read_bytes()
        session=control.Session(self.root/'cohort',[],True,True,identity={'src/service.py':'unchanged'},
            live=lambda:dict(images={'tag':['sha256:original']}))
        with session.activate():
            control.plan(['legacy'])
            with control.unit('legacy',child,dict(status='FAIL')) as unit:
                self.assertTrue(unit.skip)
                self.assertEqual(unit.result['status'],'FAIL')
        self.assertEqual((child/'summary.json').read_bytes(),original)
        self.assertEqual(control.read(session.path)['units']['legacy']['state'],'COMPLETE')

    def test_immediate_preserves_completed_units_and_partial_rows_then_retries_only_interrupted(self):
        from workloads import registration_load
        session=self.session()
        def generate(base,schedule,identity,rows):
            rows.append(dict(outcome='ACCEPTED',payload={'user_id':'already-sent'},response=dict(status=201,data={'request_id':'id'})))
            self.request(session,'immediate');session.cache_at=0
            control.immediate()
        with self.assertRaises(control.Pause),session.activate():
            with control.unit('done',self.root/'done') as unit:
                (unit.directory/'raw').write_text('keep')
                unit.complete(dict(status='FAIL'))
            with control.unit('unfinished',self.root/'unfinished') as unit,patch('workloads.guard_lab',return_value={'namespace':'csc3104-lab'}),patch(
                    'workloads.api',return_value=dict(sale_state='pre_sale',waiting_count=0)),patch('loadgen.generate',side_effect=generate):
                registration_load('fake',unit.directory,1,1)
            self.fail('Another unit started')
        ledger=control.read(session.path)
        self.assertEqual(ledger['units']['done']['state'],'COMPLETE')
        self.assertEqual(ledger['units']['unfinished']['state'],'INTERRUPTED')
        self.assertEqual(control.read(self.root/'unfinished/arrivals.json')[0]['outcome'],'ACCEPTED')
        resumed=self.session(True)
        with resumed.activate():
            with control.unit('done',self.root/'done') as unit:
                self.assertTrue(unit.skip)
                self.assertEqual(unit.result['status'],'FAIL')
            with control.unit('unfinished',self.root/'unfinished') as unit:
                self.assertNotEqual(unit.directory,self.root/'unfinished')
                (unit.directory/'raw').write_text('new attempt')
                unit.complete(dict(status='PASS'))
        self.assertEqual((self.root/'done/raw').read_text(),'keep')

    def test_safe_pause_during_full_hpa_cycle_waits_for_all_phases(self):
        session=self.session();phases=[]
        def hpa(directory,target):
            self.request(session,'safe')
            for phase in ('baseline','high','recovery','repeat','final-observation'):
                control.sleep(.001)
                phases.append(phase)
            (directory/'timeline.json').write_text('[]')
            return dict(status='PASS')
        arguments=['study.py','--case','24-api','--run','cohort','--reset-lab']
        with patch.object(sys,'argv',arguments),patch.object(study,'run_directory',return_value=session.directory),patch.object(
                study.local,'preflight'),patch('operations.hpa_trial',side_effect=hpa):
            with self.assertRaises(control.Pause),session.activate():study.main.__wrapped__()
        self.assertEqual(phases,['baseline','high','recovery','repeat','final-observation'])
        self.assertEqual(control.read(session.path)['units']['hpa-cycle']['state'],'COMPLETE')

    def test_immediate_terminates_only_owned_blocking_subprocess(self):
        session=self.session();finished=[]
        with self.assertRaises(control.Pause),session.activate():
            thread=threading.Thread(target=lambda:(time.sleep(.15),self.request(session,'immediate')))
            thread.start()
            try:
                started=time.monotonic()
                control.command(lambda *a,**k:None,[sys.executable,'-c','import time; time.sleep(60)'],capture=True)
                finished.append(True)
            finally:
                thread.join()
        self.assertLess(time.monotonic()-started,5)
        self.assertEqual(finished,[])

    def test_burst_runner_resumes_only_unfinished_trial(self):
        calls=[];session=self.session()
        @contextmanager
        def connection():yield 'fake-local-lab'
        @contextmanager
        def monitor(directory):yield []
        def load(base,directory,*args):
            calls.append(directory.name)
            result=dict(status='PASS',outcomes={})
            runtime.write_json(directory/'summary.json',result)
            if len(calls)==1:self.request(session,'safe')
            return result
        with patch.multiple(study,setup_lab=lambda *a,**k:None,lab_connection=connection,monitor=monitor,
                            preflight=lambda base:{},capture=lambda *a:{},registration_load=load):
            with self.assertRaises(control.Pause),session.activate():study.surge(session.directory,[100],3)
            resumed=self.session(True)
            with resumed.activate():result=study.surge(session.directory,[100],3)
        self.assertEqual(calls,['peak-100-repeat-1','peak-100-repeat-2','peak-100-repeat-3'])
        self.assertEqual(len(result['surge']),3)

    def test_scheduler_cli_finishes_pair_on_safe_pause_and_skips_it_on_resume(self):
        session=self.session();calls=[]
        trace=run.make_trace('F2',40,42,10)
        trace_path=self.root/'trace.json';runtime.write_json(trace_path,trace)
        @contextmanager
        def connection():yield 'fake-local-lab'
        def replay(base,data,directory,timeout):
            calls.append((data['seed'],directory.name))
            if len(calls)==1:self.request(session,'safe')
            result=dict(status='PASS',initial_fingerprint='same',trace_sha256=run.digest(data),batch_boundaries_match=True)
            runtime.write_json(directory/'summary.json',result)
            return result
        arguments=['run.py','compare','--run','cohort','--trace',str(trace_path),'--reset-lab','--seeds','2']
        with patch.object(sys,'argv',arguments),patch.object(run,'run_directory',return_value=session.directory),patch.multiple(
                run,setup_lab=lambda *a,**k:None,k=lambda *a,**k:'',lab_connection=connection,capture=lambda *a:{},
                collect_logs=lambda directory:None,replay=replay,paired_analysis=lambda r:{},write_report=lambda *a:None),patch.object(run.local,'preflight'):
            with self.assertRaises(control.Pause),session.activate():run.main.__wrapped__()
            self.assertEqual(calls,[(42,'demand-cycle'),(42,'fcfs')])
            arguments.append('--resume')
            resumed=self.session(True)
            with resumed.activate():code=run.main.__wrapped__()
        self.assertEqual(code,0)
        self.assertEqual(calls,[(42,'demand-cycle'),(42,'fcfs'),(43,'fcfs'),(43,'demand-cycle')])
        self.assertEqual(len(control.read(session.directory/'comparison.json')['results']),4)


if __name__=='__main__':unittest.main()
