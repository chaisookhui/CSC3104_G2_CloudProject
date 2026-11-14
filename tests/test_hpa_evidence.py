"""An HPA configuration or requested replica count is not a scaling result."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
from operations import hpa_transitions, hpa_cpu_evidence


class HpaEvidenceTests(unittest.TestCase):
    def point(self,t,ready,desired=4):
        return dict(monotonic=t,deployments={'items':[dict(metadata={'name':'waiting-room'},
            spec={'replicas':desired},status={'readyReplicas':ready})]})

    def test_desired_replicas_are_not_ready_replicas(self):
        result=hpa_transitions([self.point(t,1) for t in (0,11,21,31)],'waiting-room',10,20,30)
        self.assertFalse(result['scale_out'])
        self.assertFalse(result['scale_in'])
        self.assertFalse(result['repeat_scale_out'])

    def test_retained_four_replicas_cannot_pass_recovery(self):
        result=hpa_transitions([self.point(t,n) for t,n in ((0,1),(11,4),(21,4),(31,4))],
                               'waiting-room',10,20,30)
        self.assertFalse(result['scale_in'])
        self.assertFalse(result['repeat_scale_out'])

    def test_full_cycle_requires_phase_order(self):
        result=hpa_transitions([self.point(t,n) for t,n in ((0,1),(11,4),(21,2),(29,1),(31,1),(35,3))],
                               'waiting-room',10,20,30)
        self.assertTrue(all(result[k] for k in ('baseline_one','scale_out','scale_in','repeat_scale_out')))

    def cpu_point(self,t,cpu):
        return dict(monotonic=t,hpa={'items':[dict(metadata={'name':'waiting-room'},status={
            'currentMetrics':[{'resource':{'name':'cpu','current':{'averageUtilization':cpu}}}]})]})

    def test_missing_cpu_cannot_prove_load_or_recovery(self):
        null_metric=dict(monotonic=16,hpa={'items':[dict(metadata={'name':'waiting-room'},status={'currentMetrics':None})]})
        result=hpa_cpu_evidence([self.point(15,4),null_metric],'waiting-room',10,20,100)
        self.assertIsNone(result['high_peak_utilization'])
        self.assertIsNone(result['final_recovery_mean_utilization'])
        self.assertFalse(result['exceeds_target'])
        self.assertFalse(result['recovered_below_target'])

    def test_cpu_must_exceed_target_during_load_and_recover_at_end(self):
        result=hpa_cpu_evidence([self.cpu_point(15,120),self.cpu_point(25,90),self.cpu_point(80,4)],
                                'waiting-room',10,20,100)
        self.assertTrue(result['exceeds_target'])
        self.assertTrue(result['recovered_below_target'])

    def test_hot_recovery_or_only_baseline_cpu_cannot_pass(self):
        result=hpa_cpu_evidence([self.cpu_point(5,200),self.cpu_point(80,90)],'waiting-room',10,20,100)
        self.assertFalse(result['exceeds_target'])
        self.assertFalse(result['recovered_below_target'])
