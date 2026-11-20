"""Check TC-14 outcome and measurement accounting with unit-test fixtures."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from tc14_extended import classify
from tc14_report import summarize


def test_http_200_requires_a_matching_active_hold():
    response = dict(status=200, transport_error=None, response_body='{"success":false}')
    assert classify(response, 'request-1') == ('UNAVAILABLE', None, None)
    body = dict(success=True, request_id='request-1', hold_status='ACTIVE', hold_id='hold-1',
                seats=[dict(section='C', state='HELD', held_by_request_id='request-1',
                            hold_id='hold-1', seat_id='C-1-1')])
    response['response_body'] = json.dumps(body)
    assert classify(response, 'request-1') == ('RESERVED', 'hold-1', 'C-1-1')
    assert classify(response, 'different-request') == ('INVALID_RESPONSE', None, None)
    response['transport_error'] = 'IncompleteRead: partial reply'
    assert classify(response, 'request-1') == ('TRANSPORT_ERROR', None, None)


def test_warmups_failures_and_missing_checks_keep_separate_denominators():
    rows = [dict(phase=phase, outcome=outcome, latency_ms=value) for phase, outcome, value in (
        ('warmup', 'RESERVED', 200), ('measured', 'RESERVED', 10),
        ('measured', 'UNAVAILABLE', 3), ('measured', 'TRANSPORT_ERROR', 15000),
        ('measured', 'RESERVED', 20),
    )]
    result = summarize('Test', 'INCOMPLETE', rows, 5, [None])
    assert (result['successful'], result['failed'], result['missing']) == (2, 2, 1)
    assert result['failure_outcomes'] == {'UNAVAILABLE': 1, 'TRANSPORT_ERROR': 1}
    assert result['warmup_successful'] == 1
    assert result['invariant_violations'] is None
    assert result['mean_ms'] == result['median_ms'] == 15
    assert result['p95_ms'] == 19.5
    assert result['p99_ms'] == 19.9
    assert result['min_ms'] == 10 and result['max_ms'] == 20
