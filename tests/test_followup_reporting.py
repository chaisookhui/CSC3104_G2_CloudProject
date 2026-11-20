"""Completion denominators must not grow when interrupted evidence is retained."""
from pathlib import Path
import sys
import unittest
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from followup_report import burst_summary,recorded_identity_verification


class ReportingTests(unittest.TestCase):
    def test_legacy_identity_read_uses_saved_queue_but_does_not_override_explicit_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            self.assertFalse(recorded_identity_verification({},directory))
            (directory/'registered-queue.json').write_text('[]')
            self.assertTrue(recorded_identity_verification({},directory))
            self.assertFalse(recorded_identity_verification({'identity_verification_complete':False},directory))
    def test_partial_attempt_never_counts_as_completed_burst(self):
        base=dict(label='Fresh follow-up',profile='spike',duration=40,rate=100,
                  delivery_valid=True,accepted=2100,offered=2100,raw='raw/summary.json')
        rows=[dict(base,status='PASS',admission={'elapsed_seconds':180}),
              dict(base,status='INCONCLUSIVE',admission={'elapsed_seconds':601}),
              dict(base,status='INTERRUPTED',admission=None)]
        result=burst_summary(rows)[0]
        self.assertEqual(result['complete_trials'],2)
        self.assertEqual(result['passing_trials'],1)
        self.assertEqual(result['retained_partial_attempts'],1)
        self.assertEqual(result['accepted'],4200)
        self.assertEqual(result['max_admission_seconds'],601)


if __name__=='__main__':unittest.main()
