"""Check measurement denominators and unavailable values using synthetic fixtures."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from metrics import summarize


class MeasurementSummaryTests(unittest.TestCase):
    def test_errors_missing_and_business_failures_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path/'summary.json').write_text(json.dumps({'elapsed_seconds': 2, 'outcomes': {'UNAVAILABLE': 1}}))
            (path/'customers.json').write_text(json.dumps([
                {'response': {'status': 200, 'elapsed_ms': 10}},
                {'response': {'status': 503, 'elapsed_ms': 30}}, {},
            ]))
            data = summarize(path)
        self.assertEqual(data['average_response_ms'], 20)
        self.assertEqual(data['p95_response_ms'], 29)
        self.assertEqual(data['http_success_rate'], 1/3)
        self.assertEqual(data['http_error_rate'], 1/3)
        self.assertEqual(data['missing_http_samples'], 1)
        self.assertEqual(data['http_success_per_second'], .5)
        self.assertEqual(data['business_outcomes'], {'UNAVAILABLE': 1})

    def test_empty_measurements_are_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path/'summary.json').write_text('{}')
            (path/'customers.json').write_text('[]')
            data = summarize(path)
        self.assertIsNone(data['average_response_ms'])
        self.assertIsNone(data['p95_response_ms'])
        self.assertIsNone(data['http_success_rate'])
        self.assertIsNone(data['http_success_per_second'])


if __name__ == '__main__':
    unittest.main()
