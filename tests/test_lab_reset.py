"""Check reset scope and failure handling without contacting Docker/Kubernetes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'local_kubernetes', Path(__file__).resolve().parents[1] / 'infra/k8s/local.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class LabResetTests(unittest.TestCase):
    def test_main_reset_preserves_lab_and_restores_main_entry_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main_secret = root / 'secrets-csc3104.json'
            lab_secret = root / 'secrets-csc3104-lab.json'
            main_secret.write_text('main')
            lab_secret.write_text('lab')
            calls = []

            def kubectl(*args, **kwargs):
                calls.append(('kubectl', args, kwargs))

            def deploy(namespace, **kwargs):
                self.assertFalse(main_secret.exists())
                calls.append(('deploy', namespace, kwargs))

            with patch.object(local, 'LOCAL', root), patch.object(local, 'kubectl', side_effect=kubectl), \
                    patch.object(local, 'deploy', side_effect=deploy):
                local.reset_demo(batch_size=10)

            self.assertEqual(calls[0], ('kubectl', (
                'delete', 'namespace', 'csc3104', '--ignore-not-found', '--wait=true', '--timeout=180s'),
                {'namespace': None}))
            self.assertEqual(calls[1], ('deploy', 'csc3104', {'hold_ttl': 300, 'batch_size': 10}))
            self.assertEqual(calls[2][1][:3], ('patch', 'service', 'frontend'))
            self.assertEqual(calls[2][2], {'namespace': 'csc3104'})
            self.assertIn('30080', calls[2][1][-1])
            self.assertEqual(lab_secret.read_text(), 'lab')

    def test_arbitrary_namespace_reset_is_rejected_before_any_command(self):
        with patch.object(local, 'kubectl') as kubectl, patch.object(local, 'deploy') as deploy:
            with self.assertRaises(ValueError):
                local._reset_environment('another-project', 50)
            kubectl.assert_not_called()
            deploy.assert_not_called()

    def test_reset_targets_only_lab_and_waits_before_recreating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lab_secret = root / 'secrets-csc3104-lab.json'
            main_secret = root / 'secrets-csc3104.json'
            lab_secret.write_text('lab')
            main_secret.write_text('main')
            calls = []

            def delete(*args, **kwargs):
                self.assertTrue(lab_secret.exists())
                calls.append(('delete', args, kwargs))

            def deploy(namespace, **kwargs):
                self.assertFalse(lab_secret.exists())
                calls.append(('deploy', namespace, kwargs))

            with patch.object(local, 'LOCAL', root), patch.object(local, 'kubectl', side_effect=delete), \
                    patch.object(local, 'deploy', side_effect=deploy):
                local.reset_test_environment(batch_size=10)

            self.assertEqual(calls, [
                ('delete', ('delete', 'namespace', 'csc3104-lab', '--ignore-not-found',
                            '--wait=true', '--timeout=180s'), {'namespace': None}),
                ('deploy', 'csc3104-lab', {'hold_ttl': 300, 'batch_size': 10}),
            ])
            self.assertEqual(main_secret.read_text(), 'main')

    def test_failed_deletion_keeps_credentials_and_does_not_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / 'secrets-csc3104-lab.json'
            secret.write_text('keep')
            with patch.object(local, 'LOCAL', root), \
                    patch.object(local, 'kubectl', side_effect=RuntimeError('timeout')), \
                    patch.object(local, 'deploy') as deploy:
                with self.assertRaisesRegex(RuntimeError, 'timeout'):
                    local.reset_test_environment()
                deploy.assert_not_called()
            self.assertEqual(secret.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
