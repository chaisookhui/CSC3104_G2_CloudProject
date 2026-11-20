"""Summarise saved HTTP samples; reads evidence without contacting the application.

Usage: python experiments/metrics.py --run TC-14-r1
No sample data or benchmark results are invented when a measurement is missing.
"""
import argparse
import json
from pathlib import Path
import re
from statistics import mean

from workloads import percentile

ROOT = Path(__file__).resolve().parents[1]


def summarize(directory):
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    samples_path = directory / ('arrivals.json' if (directory / 'arrivals.json').exists() else 'customers.json')
    rows = json.loads(samples_path.read_text(encoding='utf-8'))
    responses = [r['response'] for r in rows if isinstance(r.get('response'), dict)]
    latencies = [r['elapsed_ms'] for r in responses if isinstance(r.get('elapsed_ms'), (int, float))]
    # HTTP success and useful reservation/confirmation are distinct measures.
    http_ok = sum(200 <= r.get('status', 0) < 300 for r in responses)
    http_error = len(responses) - http_ok
    duration = summary.get('elapsed_including_drain', summary.get('elapsed_seconds'))
    return {
        'scope': summary.get('workload', 'See source summary for workload'),
        'offered': len(rows), 'measured_http_responses': len(responses),
        'missing_http_samples': len(rows) - len(responses),
        'average_response_ms': mean(latencies) if latencies else None,
        'p95_response_ms': percentile(latencies, 95),
        'http_success_count': http_ok, 'http_error_or_transport_count': http_error,
        'http_success_rate': http_ok / len(rows) if rows else None,
        'http_error_rate': http_error / len(rows) if rows else None,
        'missing_http_sample_rate': (len(rows) - len(responses)) / len(rows) if rows else None,
        'elapsed_seconds': duration,
        'http_success_per_second': http_ok / duration if duration and duration > 0 else None,
        'business_outcomes': summary.get('outcomes'),
        'interpretation': 'HTTP 200 can mean no seats. Missing samples are separate from errors. '
                          'Contention latency covers the final HTTP attempt; total duration includes retries. '
                          'Use original customer/arrival records for reconciliation and booking goodput.'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', args.run):
        parser.error('Use the run ID, without a path')
    directory = ROOT / '.local/test-results' / args.run
    result = summarize(directory)
    path = directory / 'metrics.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    print('Saved:', path)


if __name__ == '__main__':
    main()
