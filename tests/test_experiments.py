"""Research-input reproducibility, safety boundaries and honest metric semantics."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments'))
import workloads
import runtime


class ExperimentTests(unittest.TestCase):
    def test_saved_trace_is_deterministic_and_all_scenarios_validate(self):
        for scenario in [f'F{i}' for i in range(1,8)]:
            one=workloads.make_trace(scenario,40,42)
            two=workloads.make_trace(scenario,40,42)
            self.assertEqual(workloads.digest(one),workloads.digest(two))
            self.assertEqual(workloads.validate_trace(one),one)
            self.assertNotEqual(workloads.digest(one),workloads.digest(workloads.make_trace(scenario,40,43)))

    def test_deadline_identity_compares_instants_not_timestamp_spelling(self):
        self.assertTrue(workloads.same_deadline('2026-11-10T10:00:00Z','2026-11-10T10:00:00+00:00'))
        self.assertFalse(workloads.same_deadline('2026-11-10T10:00:00Z','2026-11-10T10:00:01Z'))
        self.assertFalse(workloads.same_deadline(None,'2026-11-10T10:00:00Z'))

    def test_balanced_trace_contains_every_size_in_each_section(self):
        trace=workloads.make_trace('F1',32,42)
        self.assertEqual({(p['section'],p['party_size']) for p in trace['customers']},
                         {(section,size) for section in 'ABCD' for size in range(1,5)})

    def test_hot_section_and_size_are_independent(self):
        trace=workloads.make_trace('F4',500,42)
        sizes={p['party_size'] for p in trace['customers'] if p['section']=='A'}
        self.assertEqual(sizes,{1,2,3,4})
        self.assertGreater(sum(p['section']=='A' for p in trace['customers']),350)

    def test_invalid_duplicate_or_out_of_order_trace_is_rejected(self):
        base=workloads.make_trace(count=10)
        for field,value in [('queue_number',2),('section',None),('wave',True),('action','pay-real-money')]:
            bad=copy.deepcopy(base); bad['customers'][0][field]=value
            with self.assertRaises(ValueError): workloads.validate_trace(bad)

    def test_guard_rejects_main_even_if_port_is_lab_port(self):
        with patch.object(runtime,'api',return_value={'namespace':'csc3104','is_lab':False}):
            with self.assertRaisesRegex(RuntimeError,'not csc3104-lab'):
                runtime.guard_lab('http://127.0.0.1:18100')

    def test_guard_rejects_remote_hosts_before_http(self):
        with patch.object(runtime,'api') as api:
            with self.assertRaises(ValueError): runtime.guard_lab('https://example.com')
            api.assert_not_called()

    def test_result_path_cannot_escape_workspace(self):
        for name in ('../outside','..','C:/outside','/outside','bad/name'):
            with self.assertRaises(ValueError): runtime.run_directory(name)

    def test_free_blocks_keep_separate_rows_and_adjacency(self):
        seats=[dict(seat_id=f'A-{row}-{position}',section='A',row=row,position_in_row=position,
                    state='CONFIRMED' if position==3 else 'AVAILABLE')
               for row in (1,2) for position in range(1,6)]
        self.assertEqual(workloads.free_blocks(seats),{'A/1':[2,2],'A/2':[2,2]})

    def test_unknown_customers_remain_in_denominator_and_missing_wait_is_not_zero(self):
        rows=[dict(section='A',party_size=2,queue_number=1,outcome='UNKNOWN'),
              dict(section='A',party_size=2,queue_number=2,outcome='UNAVAILABLE',
                   allocation_state='UNAVAILABLE',decision_wait_seconds=2)]
        result=workloads.summarize(rows,[],[],10)
        self.assertEqual(result['customers'],2)
        self.assertEqual(result['groups'][0]['offered'],2)
        self.assertEqual(result['groups'][0]['unknown'],1)
        self.assertEqual(result['groups'][0]['measured_waits'],1)
        self.assertEqual(result['groups'][0]['median_wait_seconds'],2)
        self.assertIsNone(workloads.percentile([],95))

    def test_overtakes_ignore_other_sections_and_batches(self):
        rows=[dict(section='A',party_size=1,queue_number=1,batch_id='one',outcome='UNAVAILABLE',decided_at=5),
              dict(section='A',party_size=1,queue_number=2,batch_id='one',outcome='UNAVAILABLE',decided_at=3),
              dict(section='B',party_size=1,queue_number=3,batch_id='one',outcome='UNAVAILABLE',decided_at=1),
              dict(section='A',party_size=1,queue_number=4,batch_id='two',outcome='UNAVAILABLE',decided_at=1)]
        self.assertEqual(workloads.summarize(rows,[],[],10)['overtakes'],1)


if __name__=='__main__': unittest.main()
