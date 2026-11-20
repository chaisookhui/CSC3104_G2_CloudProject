"""Boundary and interpretation checks for the additional measured studies."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from fairness import fairness_summary, paired_analysis
from followup import boundary_trials, verify_recorded, planned
from followup_report import same_study
from operations import scale_api
from workloads import arrival_schedule, registration_load, validate_load


class FollowupTests(unittest.TestCase):
    def test_postload_read_failure_keeps_counts_and_never_claims_missing_ids_or_pass(self):
        def generate(base,schedule,identity,rows):
            rows.append(dict(payload={'user_id':'one'},outcome='ACCEPTED',scheduled_seconds=0,
                launched_seconds=0,phase='baseline',response=dict(status=201,data={'request_id':'r1'},elapsed_ms=10,instance='pod')))
            return dict(elapsed=1,cpu_seconds=.01,capacity=4096,peak_in_flight=1)
        with tempfile.TemporaryDirectory() as folder,patch('workloads.guard_lab',return_value={'namespace':'csc3104-lab'}),patch(
                'workloads.api',side_effect=[dict(sale_state='pre_sale',waiting_count=0),RuntimeError('queue timed out')]),patch(
                'loadgen.generate',side_effect=generate),patch('workloads.invariants',return_value={'violations':0}) as sql:
            result=registration_load('http://127.0.0.1',Path(folder),1,1)
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(result['accepted'],1)
            self.assertEqual(result['missing_acknowledged_ids'],[])
            self.assertFalse(result['identity_verification_complete'])
            self.assertTrue(result['timing_fidelity'])
            self.assertTrue((Path(folder)/'reconciliation-unavailable.json').exists())
            self.assertFalse((Path(folder)/'registered-queue.json').exists())
            sql.assert_called_once()

    def test_remaining_plan_never_repeats_completed_hpa_cycles(self):
        jobs=planned('new-prefix',skip_hpa=True)
        self.assertEqual([name for name,_ in jobs],['18-F2','18-F3','18-F6','23-grid','19-bursts'])
        self.assertEqual(len(planned('new-prefix')),9)

    def test_replacement_requires_same_trace_and_protocol(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=root/'old.json';new=root/'new.json';run=root/'replacement';run.mkdir()
            old.write_text('{"scenario":"F2"}');new.write_text(old.read_text())
            (run/'run.json').write_text(json.dumps({'commands':[{'arguments':dict(command='compare',trace=str(new),seeds=10,reset_lab=True)}]}))
            command=[sys.executable,'experiments/run.py','compare','--trace',str(old),'--seeds','10','--reset-lab','--run','original']
            self.assertTrue(same_study(command,run))
            new.write_text('{"scenario":"F3"}')
            self.assertFalse(same_study(command,run))

    def test_high_rate_opt_in_keeps_every_other_limit(self):
        for rate in (250,300):
            with self.assertRaises(ValueError):validate_load(rate,30)
            validate_load(rate,30,True)
        for rate,duration in ((301,30),(300,301),(300,67),(0,30)):
            with self.assertRaises(ValueError):validate_load(rate,duration,True)
        validate_load(200,30)

    def test_invalid_trial_never_connects_or_resets(self):
        with tempfile.TemporaryDirectory() as name, patch('operations.setup_lab') as setup:
            with self.assertRaises(ValueError):scale_api(Path(name),rates=[250])
            setup.assert_not_called()
        with patch('workloads.guard_lab') as guard:
            with self.assertRaises(ValueError):registration_load('http://127.0.0.1',None,250,30)
            guard.assert_not_called()

    def test_original_and_extended_schedules_are_exact(self):
        for rate,total in ((100,2100),(150,3100),(200,4100)):
            schedule=arrival_schedule(rate,40,'spike')
            self.assertEqual(len(schedule),total)
            self.assertEqual(sum(phase=='surge' for _,phase in schedule),20*rate)
            self.assertEqual(sum(t<10 for t,_ in schedule),50)
            self.assertEqual(sum(t>=30 for t,_ in schedule),50)
        for rate in (200,250,300):
            self.assertEqual(len(arrival_schedule(rate,30,'constant')),rate*30)
        self.assertEqual(len(arrival_schedule(100,180,'spike')),9450)

    def test_partial_or_unknown_strata_never_produce_jain(self):
        groups=[dict(section='A',party_size=n,reservation_rate=1,unknown=0,offered=10) for n in (1,2,3)]
        value=fairness_summary(groups)['sections'][0]
        self.assertIsNone(value['jain_reservation_rates'])
        self.assertEqual(value['missing_sizes'],[4])
        groups.append(dict(section='A',party_size=4,reservation_rate=1,unknown=1,offered=1))
        self.assertIsNone(fairness_summary(groups)['sections'][0]['jain_reservation_rates'])

    def test_pair_must_match_trace_inventory_and_boundaries(self):
        groups=[dict(section='A',party_size=n,reservation_rate=1,unknown=0) for n in range(1,5)]
        result=dict(status='PASS',initial_fingerprint='same',trace_sha256='same',batch_boundaries_match=True,
                    fairness=fairness_summary(groups))
        entries=[dict(seed=42,repeat=1,policy=p,result=copy.deepcopy(result)) for p in ('demand-cycle','fcfs')]
        self.assertEqual(len(paired_analysis(entries)['pairs']),1)
        for key,value in (('trace_sha256','different'),('initial_fingerprint','different'),('batch_boundaries_match',False)):
            bad=copy.deepcopy(entries);bad[1]['result'][key]=value
            self.assertEqual(paired_analysis(bad)['pairs'],[])

    def test_boundary_repetitions_exclude_invalid_delivery(self):
        grid=[dict(replicas=1,rate=rate,timing_fidelity=valid,scheduled=30*rate,offered=30*rate,
                   launched=30*rate,generator_dropped=0,sustainable=passing)
              for rate,valid,passing in ((200,True,True),(250,False,False),(300,True,False))]
        jobs=boundary_trials(grid)
        self.assertEqual([name for name,_ in jobs],['23-boundary-n1-rate200','23-boundary-n1-rate300'])
        self.assertTrue(all(cmd[cmd.index('--repeats')+1]=='2' for _,cmd in jobs))

    def test_completed_attempt_adoption_requires_matching_conditions(self):
        arguments=['experiments/study.py','--case','capacity','--rates','200','250','--reset-lab','--run','example']
        manifest={'arguments':dict(case='capacity',rates=[200,250],reset_lab=True,run='example')}
        verify_recorded(arguments,manifest)
        manifest['arguments']['rates']=[200,300]
        with self.assertRaisesRegex(ValueError,'conditions differ'):
            verify_recorded(arguments,manifest)


if __name__=='__main__':unittest.main()
