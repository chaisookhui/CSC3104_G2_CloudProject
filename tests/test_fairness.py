import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from fairness import fairness_summary

class FairnessTests(unittest.TestCase):
    def groups(self,rates,unknown=0):
        return [dict(section='A',party_size=i+1,reservation_rate=r,unknown=unknown) for i,r in enumerate(rates)]
    def test_equal_rates_have_zero_gap_and_jain_one(self):
        value=fairness_summary(self.groups([.5]*4))['sections'][0]
        self.assertEqual(value['reservation_rate_gap'],0)
        self.assertEqual(value['jain_reservation_rates'],1)
        self.assertTrue(value['interpretable'])
    def test_zero_service_and_missing_or_unknown_groups_are_not_evidence(self):
        for groups in (self.groups([0]*4),self.groups([1]*3),self.groups([1]*4,1)):
            self.assertFalse(fairness_summary(groups)['sections'][0]['interpretable'])
    def test_size_starvation_is_visible(self):
        value=fairness_summary(self.groups([1,0,0,0]))['sections'][0]
        self.assertEqual(value['reservation_rate_gap'],1)
        self.assertEqual(value['jain_reservation_rates'],.25)

if __name__=='__main__':unittest.main()
