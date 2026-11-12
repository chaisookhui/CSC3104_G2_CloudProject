"""A load generator must not pass a trial in which every customer was rejected."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
import workloads

class LoadCompletenessTests(unittest.TestCase):
    def test_spike_schedule_has_exact_phase_counts_without_float_boundary_loss(self):
        schedule=workloads.arrival_schedule(100,40,'spike')
        self.assertEqual(len(schedule),2100)
        self.assertEqual(sum(phase=='surge' for _,phase in schedule),2000)
        self.assertEqual(sum(phase=='baseline' for _,phase in schedule),100)
        self.assertEqual(len({t for t,_ in schedule}),2100)
    def test_rejected_customers_do_not_produce_a_false_pass(self):
        def api(base,path):
            return dict(sale_state='pre_sale',waiting_count=0) if path.endswith('status') else dict(requests=[])
        with tempfile.TemporaryDirectory() as folder,patch.object(workloads,'guard_lab',return_value={'namespace':'csc3104-lab'}),patch.object(workloads,'api',side_effect=api),patch.object(workloads,'request',return_value=dict(status=429,data={},elapsed_ms=2)):
            result=workloads.registration_load('http://127.0.0.1:1',Path(folder),rate=1,duration=1)
        self.assertEqual(result['outcomes'],{'REJECTED':1})
        self.assertEqual(result['status'],'INCONCLUSIVE')

if __name__=='__main__':unittest.main()
