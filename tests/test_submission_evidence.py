"""Evidence repackaging must reject tampering and real source changes."""
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from build_submission import PREFIX, authoring_only, read_export_entry, sha, validated_source_bytes


class SubmissionEvidenceTests(unittest.TestCase):
    def test_repackaging_rejects_altered_and_unmanifested_evidence(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(PREFIX + 'raw.json', json.dumps({'status': 'FAIL'}))
        stream.seek(0)
        manifest = {'raw.json': {'sha256': sha(b'{"status": "PASS"}'), 'bytes': 18}}
        with zipfile.ZipFile(stream) as archive:
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                read_export_entry(archive, PREFIX + 'raw.json', manifest)
            with self.assertRaisesRegex(ValueError, 'missing from input manifest'):
                read_export_entry(archive, PREFIX + 'raw.json', {})

    def test_windows_newlines_do_not_allow_changed_application_content(self):
        recorded = b'retry = True\r\n'
        self.assertEqual(validated_source_bytes(b'retry = True\n', recorded, sha(recorded)), recorded)
        with self.assertRaisesRegex(ValueError, 'source content differs'):
            validated_source_bytes(b'retry = False\n', recorded, sha(recorded))
        with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
            validated_source_bytes(recorded, recorded, sha(b'changed'))

    def test_filter_keeps_failure_and_interruption_evidence(self):
        for path in ('run/interrupted.json', 'run/partial-results.json', 'run/failed.log',
                     'report/raw-audit.json', 'run/run.json', 'run/harness.py'):
            self.assertFalse(authoring_only(path))
        self.assertTrue(authoring_only('report/CHECKPOINT.md'))
        self.assertTrue(authoring_only('docs/FOLLOWUP_TESTING_APPENDIX.md'))


if __name__ == '__main__':
    unittest.main()
