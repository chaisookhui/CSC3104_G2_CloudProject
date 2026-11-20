"""A load generator must not pass a trial in which every customer was rejected."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
import workloads
import loadgen

class LoadCompletenessTests(unittest.TestCase):
    def test_terminal_reply_after_admission_deadline_cannot_pass(self):
        clock=[0]
        reads=[0]
        def generate(base,schedule,identity,rows):
            rows.append(dict(payload={'user_id':'one'},scheduled_seconds=0,launched_seconds=0,
                phase='baseline',outcome='ACCEPTED',response=dict(status=201,data={'request_id':'r1'},elapsed_ms=2)))
            return dict(elapsed=1,capacity=4096,peak_in_flight=1,cpu_seconds=.01)
        def api(base,path,body=None):
            if path.endswith('status'):return dict(sale_state='pre_sale',waiting_count=0)
            if path.endswith('sale/start'):return dict(sale_state='sale_started')
            reads[0]+=1
            if reads[0]>=3:clock[0]=2
            return dict(requests=[dict(user_id='one',request_id='r1',queue_number=1,
                status='UNAVAILABLE' if reads[0]>=3 else 'QUEUED')])
        with tempfile.TemporaryDirectory() as folder,patch.object(loadgen,'generate',side_effect=generate),patch.object(workloads,'invariants',return_value={'violations':0}),patch.object(workloads,'guard_lab',return_value={'namespace':'csc3104-lab'}),patch.object(workloads,'api',side_effect=api),patch.object(workloads.time,'monotonic',side_effect=lambda:clock[0]),patch.object(workloads.time,'perf_counter',side_effect=lambda:clock[0]):
            result=workloads.registration_load('http://127.0.0.1:1',Path(folder),rate=1,duration=1,admit=True,timeout=1)
            self.assertTrue((Path(folder)/'numbered-queue.json').exists())
        self.assertEqual(result['admission']['unresolved_ids'],[])
        self.assertFalse(result['admission']['within_deadline'])
        self.assertEqual(result['status'],'INCONCLUSIVE')

    def test_partial_generator_output_cannot_pass_the_original_schedule(self):
        def generate(base,schedule,identity,rows):
            rows.append(dict(payload={'user_id':'one'},scheduled_seconds=0,launched_seconds=0,
                phase='baseline',outcome='ACCEPTED',response=dict(status=201,data={'request_id':'r1'},elapsed_ms=2)))
            return dict(elapsed=1,capacity=4096,peak_in_flight=1,cpu_seconds=.01)
        def api(base,path):
            return dict(sale_state='pre_sale',waiting_count=0) if path.endswith('status') else dict(requests=[{'request_id':'r1','user_id':'one'}])
        with tempfile.TemporaryDirectory() as folder,patch.object(loadgen,'generate',side_effect=generate),patch.object(workloads,'invariants',return_value={'violations':0}),patch.object(workloads,'guard_lab',return_value={'namespace':'csc3104-lab'}),patch.object(workloads,'api',side_effect=api):
            result=workloads.registration_load('http://127.0.0.1:1',Path(folder),rate=2,duration=1)
        self.assertEqual(result['scheduled'],2)
        self.assertEqual(result['accepted'],1)
        self.assertEqual(result['status'],'INCONCLUSIVE')

    def test_spike_schedule_has_exact_phase_counts_without_float_boundary_loss(self):
        schedule=workloads.arrival_schedule(100,40,'spike')
        self.assertEqual(len(schedule),2100)
        self.assertEqual(sum(phase=='surge' for _,phase in schedule),2000)
        self.assertEqual(sum(phase=='baseline' for _,phase in schedule),100)
        self.assertEqual(len({t for t,_ in schedule}),2100)
    def test_rejected_customers_do_not_produce_a_false_pass(self):
        def api(base,path):
            return dict(sale_state='pre_sale',waiting_count=0) if path.endswith('status') else dict(requests=[])
        def generate(base,schedule,identity,rows):
            rows.append(dict(payload={'user_id':'rejected'},scheduled_seconds=0,launched_seconds=0,phase='baseline',outcome='REJECTED',response=dict(status=429,data={},elapsed_ms=2)))
            return dict(elapsed=1,capacity=4096,peak_in_flight=1,cpu_seconds=.01)
        with tempfile.TemporaryDirectory() as folder,patch.object(loadgen,'generate',side_effect=generate),patch.object(workloads,'invariants',return_value={'violations':0}),patch.object(workloads,'guard_lab',return_value={'namespace':'csc3104-lab'}),patch.object(workloads,'api',side_effect=api),patch.object(workloads,'request',return_value=dict(status=429,data={},elapsed_ms=2)):
            result=workloads.registration_load('http://127.0.0.1:1',Path(folder),rate=1,duration=1)
        self.assertEqual(result['outcomes'],{'REJECTED':1})
        self.assertEqual(result['status'],'INCONCLUSIVE')

if __name__=='__main__':unittest.main()
