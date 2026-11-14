"""Stored PASS labels and a later recovery cannot replace raw acceptance data."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from operations import finalize_hpa


class HpaFinalizationTests(unittest.TestCase):
    def files(self,root,rows=False):
        phases={'baseline':{'monotonic':0},'high':{'monotonic':120},
                'recovery':{'monotonic':300},'repeat':{'monotonic':900}}
        (root/'phases.json').write_text(json.dumps(phases))
        for name in ('baseline','high','repeat'):
            p=root/name;p.mkdir()
            (p/'summary.json').write_text('{"status":"PASS"}')
            (p/'arrivals.json').write_text(json.dumps([dict(outcome='ACCEPTED',stored_request_id=name,
                phase='baseline' if name=='baseline' else 'surge',scheduled_seconds=0,launched_seconds=0,
                response={'status':201})] if rows else []))
        return [dict(monotonic=800,backlog={}),dict(monotonic=1085,backlog={})]

    def assessment(self,root,samples,target):
        transitions=dict(baseline_one=True,scale_out=True,scale_in=True,repeat_scale_out=True)
        cpu=dict(exceeds_target=True,recovered_below_target=True)
        after={'observations':{'queue':{'status':200,'data':{'requests':[{'request_id':n}for n in ('baseline','high','repeat')]}}}}
        with patch('operations.hpa_transitions',return_value=transitions),patch('operations.hpa_cpu_evidence',return_value=cpu),patch('operations.invariants',return_value={'violations':0}),patch('operations.capture',return_value=after):
            return finalize_hpa(root,target,'http://127.0.0.1:1',samples)

    def test_pass_summaries_without_the_original_arrivals_do_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);samples=self.files(root)
            result=self.assessment(root,samples,'waiting-room')
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertTrue(all(not c['meets_delivery'] for c in result['phase_checks'].values()))

    def test_extended_cycle_cannot_erase_a_missed_ten_minute_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);samples=self.files(root,True)
            (root/'ten-minute-checkpoint.json').write_text(json.dumps(dict(unresolved_ids=[],window_met=False,ready_replicas=2)))
            (root/'extended-drain.json').write_text('{"drained":true}')
            def schedule(rate,duration,profile):return [(0,'baseline' if profile=='constant' else 'surge')]
            with patch('operations.arrival_schedule',side_effect=schedule):
                result=self.assessment(root,samples,'allocation-worker')
            self.assertEqual(result['extended_cycle_status'],'PASS')
            self.assertEqual(result['status'],'INCONCLUSIVE')
