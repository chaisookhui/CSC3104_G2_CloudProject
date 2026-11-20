"""Read/reject checks through a loopback frontend; never starts a sale or books seats."""
import argparse
import json
from urllib.parse import urlparse

from docker_booking_smoke import BookingCheck


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:18100')
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost'):
        parser.error('Use an HTTP loopback demo address')
    check = BookingCheck(args.base_url, 30)
    before = check.request('waiting-room/queue')['count']
    results = []
    base = {'user_id': check.prefix+'-invalid', 'section': 'A', 'party_size': 2}
    for label, body in (
        ('size-zero', {**base, 'party_size': 0}),
        ('size-five', {**base, 'party_size': 5}),
        ('boolean-size', {**base, 'party_size': True}),
        ('unknown-section', {**base, 'section': 'Z'}),
        ('empty-user', {**base, 'user_id': ''}),
        ('missing-fields', {}),
    ):
        check.request('waiting-room/submit', body, expected=400)
        results.append({'input': label, 'expected_http': 400, 'result': 'PASS'})
    check.request('waiting-room/requests/'+check.prefix+'-missing', expected=404)
    check.request('seats/seats/Z', expected=404)
    after = check.request('waiting-room/queue')['count']
    assert after == before, ('Invalid inputs changed queue count; run without concurrent writers', before, after)
    print(json.dumps({'status': 'PASS', 'checks': results, 'unknown_reads_http': 404,
                      'queue_count_before': before, 'queue_count_after': after}, indent=2))


if __name__ == '__main__':
    main()
