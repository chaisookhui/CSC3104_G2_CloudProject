"""Resume preserves failed trials and never overwrites an interrupted workload."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from operations import scale_api


class ResumeTests(unittest.TestCase):
    def cohort(self,root):
        paths=[]
        for replicas in (1,2,4):
            p=root/f'rate-50-repeat-1-replicas-{replicas}';p.mkdir();paths.append(p)
            (p/'summary.json').write_text(json.dumps(dict(rate=50,duration=30,replicas=replicas,repeat=1,
                profile='constant',status='INCONCLUSIVE' if replicas==2 else 'PASS')))
            (p/'before.json').write_text(json.dumps({'pods':[dict(name=n+'-pod',containers=[{'imageID':'sha256:'+n}])
                for n in ('waiting-room','frontend','dispatcher-worker','allocation-worker','seat-api','payment-api')]}))
        return paths

    def test_prior_inconclusive_is_preserved_without_rerunning(self):
        with tempfile.TemporaryDirectory() as folder,patch('operations.setup_lab') as setup:
            root=Path(folder);paths=self.cohort(root)
            original=(paths[1]/'summary.json').read_bytes()
            result=scale_api(root,repeats=1,resume=True)
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(len(result['results']),3)
            self.assertEqual((paths[1]/'summary.json').read_bytes(),original)
            setup.assert_not_called()

    def test_partial_workload_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder,patch('operations.setup_lab') as setup:
            root=Path(folder);paths=self.cohort(root)
            (paths[1]/'summary.json').unlink()
            (paths[1]/'arrivals.json').write_text('[{"outcome":"UNKNOWN"}]')
            with self.assertRaisesRegex(RuntimeError,'incomplete trial'):
                scale_api(root,repeats=1,resume=True)
            self.assertTrue((paths[1]/'arrivals.json').exists())
            setup.assert_not_called()

    def test_different_build_or_conditions_cannot_be_combined(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=self.cohort(root)
            d=json.loads((paths[1]/'before.json').read_text());d['pods'][0]['containers'][0]['imageID']='different'
            (paths[1]/'before.json').write_text(json.dumps(d))
            with self.assertRaisesRegex(RuntimeError,'images differ'):
                scale_api(root,repeats=1,resume=True)
