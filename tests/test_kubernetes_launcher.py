"""Exercise compatibility, tool integrity and failure recovery without a cluster."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError


spec = importlib.util.spec_from_file_location(
    'portable_kubernetes', Path(__file__).resolve().parents[1] / 'infra/k8s/local.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class PrerequisiteTests(unittest.TestCase):
    def check(self, **changes):
        info = dict(OSType='linux', ServerVersion='24.0.7', NCPU=4,
                    MemTotal=8 * 1024**3, CgroupVersion='1')
        info.update(changes)
        with patch.object(local.shutil, 'which', return_value='docker'), \
                patch.object(local, 'run', side_effect=[json.dumps(info), '2.23.0']):
            local.preflight()

    def test_docker_24_and_cgroup_v1_are_accepted(self):
        self.check()

    def test_modern_docker_and_cgroup_v2_are_accepted(self):
        self.check(ServerVersion='29.9.3', CgroupVersion='2')

    def test_windows_containers_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Linux containers'):
            self.check(OSType='windows')

    def test_old_engine_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '24.0'):
            self.check(ServerVersion='20.10.0')

    def test_insufficient_memory_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '4 GiB'):
            self.check(MemTotal=2 * 1024**3)

    def test_docker_not_running_has_actionable_error(self):
        with patch.object(local.shutil, 'which', return_value='docker'), \
                patch.object(local, 'run', side_effect=RuntimeError('connection refused')):
            with self.assertRaisesRegex(RuntimeError, 'Start Docker Desktop'):
                local.preflight()

    def test_check_does_not_build_or_create_cluster(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local, 'LOCAL', Path(directory)), \
                patch.object(local.sys, 'argv', ['local.py', '--check']), \
                patch.object(local, 'preflight'), patch.object(local, 'kubectl_binary'), \
                patch.object(local, 'kind_binary'), patch.object(local, 'run') as run, \
                patch.object(local, 'cluster') as cluster:
            local.main()
            run.assert_not_called()
            cluster.assert_not_called()

    def test_prerequisite_failure_prevents_builds_and_downloads(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local, 'LOCAL', Path(directory)), \
                patch.object(local.sys, 'argv', ['local.py']), \
                patch.object(local, 'preflight', side_effect=RuntimeError('wrong runtime')), \
                patch.object(local, 'tool_binary') as tool, patch.object(local, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'wrong runtime'):
                local.main()
            tool.assert_not_called()
            run.assert_not_called()


class ImageLoadingTests(unittest.TestCase):
    def exercise_export(self, api, help_text, fail=False):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'images.tar'
            archive.write_bytes(b'partial archive')
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if command[1:3] == ['version', '--format']:
                    return api
                if command[1:3] == ['image', 'save']:
                    if '--help' in command:
                        return help_text
                    if fail:
                        raise RuntimeError('export failed')
                return ''

            with patch.object(local, 'LOCAL', Path(directory)), \
                    patch.object(local, 'kubectl', return_value='amd64'), \
                    patch.object(local, 'run', side_effect=run):
                if fail:
                    with self.assertRaisesRegex(RuntimeError, 'export failed'):
                        local.load_images('kind')
                else:
                    local.load_images('kind')
            self.assertFalse(archive.exists(), 'large temporary archives must be removed')
            return calls

    def test_engine_24_uses_classic_export(self):
        calls = self.exercise_export('1.43', '--output')
        self.assertNotIn('--platform', calls[-2])
        self.assertEqual(calls[-1][:3], ['kind', 'load', 'image-archive'])

    def test_modern_engine_selects_node_platform(self):
        calls = self.exercise_export('1.56', '--platform --output')
        self.assertEqual(calls[-2][3:5], ['--platform', 'linux/amd64'])

    def test_modern_cli_with_older_server_omits_unsupported_option(self):
        calls = self.exercise_export('1.43', '--platform --output')
        self.assertNotIn('--platform', calls[-2])

    def test_old_cli_with_modern_server_omits_unsupported_option(self):
        calls = self.exercise_export('1.56', '--output')
        self.assertNotIn('--platform', calls[-2])

    def test_failed_export_is_not_loaded_and_archive_is_removed(self):
        calls = self.exercise_export('1.43', '--output', fail=True)
        self.assertFalse(any(command[:2] == ['kind', 'load'] for command in calls))


class ToolIntegrityTests(unittest.TestCase):
    def setUp(self):
        local.tool_binary.cache_clear()
        self.addCleanup(local.tool_binary.cache_clear)

    def prepare(self, payload, checksum_payload=None):
        digest = hashlib.sha256(checksum_payload or payload).hexdigest()
        return patch.dict(local.TOOL_CHECKSUMS, {'linux-arm64': (digest, digest)})

    def test_download_is_pinned_checked_and_reused_without_path_tools(self):
        payload = b'verified executable'
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local, 'ROOT', Path(directory)), \
                patch.object(local.platform, 'system', return_value='Linux'), \
                patch.object(local.platform, 'machine', return_value='aarch64'), \
                self.prepare(payload), \
                patch.object(local, 'urlopen', return_value=io.BytesIO(payload)) as download, \
                patch.object(local.shutil, 'which') as which:
            executable = local.kubectl_binary()
            self.assertEqual(executable.read_bytes(), payload)
            self.assertIn('v1.36.4/bin/linux/arm64/kubectl', download.call_args.args[0])
            local.tool_binary.cache_clear()
            self.assertEqual(local.kubectl_binary(), executable)
            download.assert_called_once()
            which.assert_not_called()

    def test_bad_download_never_becomes_executable(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local, 'ROOT', Path(directory)), \
                patch.object(local.platform, 'system', return_value='Linux'), \
                patch.object(local.platform, 'machine', return_value='arm64'), \
                self.prepare(b'bad', b'expected'), \
                patch.object(local, 'urlopen', return_value=io.BytesIO(b'bad')):
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                local.kind_binary()
            self.assertEqual(list((Path(directory) / '.local/bin').iterdir()), [])

    def test_tampered_cached_tool_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local, 'ROOT', Path(directory)), \
                patch.object(local.platform, 'system', return_value='Linux'), \
                patch.object(local.platform, 'machine', return_value='arm64'), \
                self.prepare(b'expected'), patch.object(local, 'urlopen') as download:
            binary = Path(directory) / '.local/bin/kind-v0.33.0-linux-arm64'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                local.kind_binary()
            download.assert_not_called()

    def test_windows_certificate_fallback_keeps_tls_verification(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local.platform, 'system', return_value='Windows'), \
                patch.object(local, 'urlopen', side_effect=URLError(ssl.SSLCertVerificationError())), \
                patch.object(local.shutil, 'which', return_value='curl.exe'), \
                patch.object(local.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as curl:
            local.download_tool('https://official.example/tool', Path(directory) / 'tool.download')
            command = curl.call_args.args[0]
            self.assertIn('--fail', command)
            self.assertNotIn('--insecure', command)
            self.assertNotIn('-k', command)

    def test_other_network_failure_does_not_try_certificate_fallback(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local.platform, 'system', return_value='Windows'), \
                patch.object(local, 'urlopen', side_effect=URLError('connection refused')), \
                patch.object(local.shutil, 'which', return_value='curl.exe'), \
                patch.object(local.subprocess, 'run') as curl:
            with self.assertRaisesRegex(RuntimeError, 'Check internet'):
                local.download_tool('https://official.example/tool', Path(directory) / 'tool.download')
            curl.assert_not_called()


class ClusterRecoveryTests(unittest.TestCase):
    def test_existing_cluster_refreshes_stale_kubeconfig_without_deletion(self):
        with patch.object(local, 'run', side_effect=['csc3104', '']) as run, \
                patch.object(local, 'kubectl'):
            local.cluster('kind')
        self.assertEqual(run.call_args_list[1].args[0][1:3], ['export', 'kubeconfig'])

    def test_failed_startup_retains_node_and_exports_logs(self):
        with patch.object(local, 'run', side_effect=['', RuntimeError('startup failed'), 0]) as run, \
                patch.object(local, 'kubectl') as kubectl:
            with self.assertRaisesRegex(RuntimeError, 'node was retained'):
                local.cluster('kind')
        self.assertIn('--retain', run.call_args_list[1].args[0])
        self.assertEqual(run.call_args_list[2].args[0][1:3], ['export', 'logs'])
        self.assertFalse(any('delete' in call.args[0] for call in run.call_args_list))
        kubectl.assert_not_called()


if __name__ == '__main__':
    unittest.main()
