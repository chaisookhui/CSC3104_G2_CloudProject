"""Real-network acceptance through the frontend proxy; no storage resets.

Run only against a dedicated fresh stack. Creates real mock bookings, including
confirmed seats. Uses standard Python only, so no test dependency install is needed.
"""
import argparse
import json
import time
from datetime import datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


class BookingCheck:
    def __init__(self, base_url, timeout):
        self.base = base_url.rstrip('/')
        self.timeout = timeout
        self.prefix = 'docker-check-' + uuid4().hex[:12]

    def request(self, path, body=None, expected=200):
        data = None if body is None else json.dumps(body).encode()
        req = Request(self.base + '/api/' + path, data=data,
                      headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=15) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        allowed = (expected,) if isinstance(expected, int) else expected
        assert status in allowed, (path, status, raw.decode()[:300])
        return json.loads(raw)

    def until(self, read, predicate):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            value = read()
            if predicate(value):
                return value
            time.sleep(.4)
        raise AssertionError(('Timed out waiting for outcome', value))

    def register(self, label, section, size=2):
        body = dict(user_id=self.prefix + '-' + label, section=section, party_size=size)
        party = self.request('waiting-room/submit', body, expected=201)
        assert self.request('waiting-room/submit', body)['request_id'] == party['request_id']
        return party['request_id']

    def reserved(self, rid):
        party = self.until(lambda: self.request('waiting-room/requests/' + rid),
                           lambda x: x['status'] in ('RESERVED', 'UNAVAILABLE'))
        assert party['status'] == 'RESERVED', party
        assert len(party['allocation']['seats']) == party['party_size']
        return party['allocation']

    def checkout(self, rid):
        return self.request('waiting-room/requests/' + rid + '/checkout')

    def pay(self, rid, allocation, outcome, key):
        return self.request('payment/payments', dict(request_id=rid,
            hold_id=allocation['hold_id'], outcome=outcome, attempt_key=key))

    def payment_done(self, payment, status):
        return self.until(lambda: self.request('payment/payments/' + payment['payment_id']),
                          lambda x: x['status'] == status)

    def cancel(self, rid):
        body = {'action_key': 'cancel-' + rid}
        action = self.request('waiting-room/requests/' + rid + '/cancel', body, expected=(200, 202))
        replay = self.request('waiting-room/requests/' + rid + '/cancel', body, expected=(200, 202))
        assert replay['action_id'] == action['action_id']
        self.until(lambda: self.checkout(rid), lambda x: x['booking_status'] == 'cancelled')

    def run(self):
        state = self.request('waiting-room/status')
        assert state['sale_state'] == 'pre_sale', 'Use a fresh dedicated stack; this check never resets data'
        assert state['storage'] == 'redis'
        assert state['waiting_count'] == 0, 'Use a dedicated empty stack'
        with urlopen(self.base + '/', timeout=10) as response:
            assert b'checkout.js' in response.read()
        for asset in ('app.js', 'checkout.js', 'checkout.css', 'seats.js'):
            with urlopen(self.base + '/' + asset, timeout=10) as response:
                assert response.status == 200 and response.read()
        for service in ('allocation', 'payment', 'dispatcher'):
            self.request(service + '/ready')

        ids = {label: self.register(label, section) for label, section in
               (('success', 'A'), ('decline', 'B'), ('cancel', 'C'), ('expiry', 'D'))}
        self.request('waiting-room/sale/start', {})
        allocations = {label: self.reserved(rid) for label, rid in ids.items()}
        assert len({x['hold_id'] for x in allocations.values()}) == 4
        print('PASS: frontend assets/proxy, Redis registration, duplicate submission, sale, dispatcher and allocation workers', flush=True)

        rid, allocation = ids['success'], allocations['success']
        first = self.pay(rid, allocation, 'success', 'success')
        assert self.pay(rid, allocation, 'success', 'success')['payment_id'] == first['payment_id']
        self.payment_done(first, 'confirmed')
        checkout = self.checkout(rid)
        assert checkout['booking_status'] == 'confirmed'
        assert checkout['hold_id'] == allocation['hold_id']
        seats = self.request('seats/seats/A')
        assert all(s['state'] == 'CONFIRMED' for s in seats if s['seat_id'] in allocation['seats'])
        print('PASS: payment worker confirms the exact seats; duplicate payment creates no second attempt', flush=True)

        rid, allocation = ids['decline'], allocations['decline']
        self.payment_done(self.pay(rid, allocation, 'decline', 'decline'), 'failed')
        checkout = self.checkout(rid)
        assert checkout['booking_status'] == 'active'
        assert datetime.fromisoformat(checkout['original_hold_expiry']) == datetime.fromisoformat(allocation['hold_expiry'])
        self.payment_done(self.pay(rid, allocation, 'success', 'retry'), 'confirmed')
        print('PASS: declined payment retries without extending the original hold', flush=True)

        self.cancel(ids['cancel'])
        seats = self.request('seats/seats/C')
        assert all(s['state'] == 'AVAILABLE' for s in seats if s['seat_id'] in allocations['cancel']['seats'])
        print('PASS: waiting-room cancellation passes the internal token and releases the whole party', flush=True)

        # Ten C seats cannot fit three parties of four. The queue order is FCFS for
        # these latecomers of equal size, so the final request must be UNAVAILABLE.
        fillers = [self.register('capacity-' + str(i), 'C', 4) for i in range(3)]
        for rid in fillers[:2]:
            self.reserved(rid)
        failed = self.until(lambda: self.request('waiting-room/requests/' + fillers[2]),
                            lambda x: x['status'] == 'UNAVAILABLE')
        assert failed['entry_type'] == 'latecomer'
        for rid in fillers[:2]:
            self.cancel(rid)
        print('PASS: latecomers dispatch automatically; no adjacent capacity yields UNAVAILABLE, not partial seats', flush=True)

        rid, allocation = ids['expiry'], allocations['expiry']
        self.until(lambda: self.checkout(rid), lambda x: x['booking_status'] == 'expired')
        self.request('payment/payments', dict(request_id=rid, hold_id=allocation['hold_id'],
            outcome='success', attempt_key='too-late'), expected=409)
        seats = self.request('seats/seats/D')
        assert all(s['state'] == 'AVAILABLE' for s in seats if s['seat_id'] in allocation['seats'])
        self.until(lambda: self.request('dispatcher/status'), lambda x: x['current'] is None)
        print('PASS: expiry worker releases seats; late payment is rejected; dispatcher completes its batches', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:18081')
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--allow-bookings', action='store_true', help='Required: this creates real mock bookings')
    args = parser.parse_args()
    if not args.allow_bookings:
        parser.error('Use --allow-bookings with a dedicated fresh test stack')
    BookingCheck(args.base_url, args.timeout).run()
