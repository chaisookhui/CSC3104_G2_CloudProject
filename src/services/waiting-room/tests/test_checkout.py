import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from queue_store import MemoryStore


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.network = Mock()
        self.app = create_app(self.store, self.network)
        self.client = self.app.test_client()
        self.old = self.client.post('/submit', json={'user_id': 'u', 'section': 'D', 'party_size': 2}).json
        with patch('app.requests.post') as post:
            post.return_value.json.return_value = {}
            self.assertEqual(self.client.post('/sale/start').status_code, 200)
        self.rid = self.old['request_id']
        self.path = '/requests/' + self.rid
        self.client.post('/queue/claim', json={'batch_id': 'b1', 'request_ids': [self.rid]})

    def finish(self, status='UNAVAILABLE', allocation=None):
        outcome = {'request_id': self.rid, 'status': status}
        if allocation is not None:
            outcome['allocation'] = allocation
        return self.client.post('/queue/outcomes', json={'batch_id': 'b1', 'outcomes': [outcome]})

    def test_unavailable_requires_explicit_idempotent_rejoin(self):
        self.assertEqual(self.finish().status_code, 200)
        again = self.client.post('/submit', json={'user_id': 'u', 'section': 'A', 'party_size': 1}).json
        self.assertEqual(again['request_id'], self.rid)
        self.assertEqual(again['status'], 'UNAVAILABLE')
        rejoined = self.client.post(self.path + '/rejoin', json={})
        self.assertEqual(rejoined.status_code, 201)
        self.assertEqual(rejoined.json['queue_number'], 2)
        self.assertEqual(self.client.post(self.path + '/rejoin', json={}).json, rejoined.json)
        active = self.client.post('/submit', json={'user_id': 'u', 'section': 'A', 'party_size': 1})
        self.assertEqual(active.json['request_id'], rejoined.json['request_id'])

    def test_invalid_or_conflicting_checkout_identity_cannot_change_outcome(self):
        allocation = {'hold_id': str(uuid4()), 'hold_status': 'ACTIVE',
                      'hold_expiry': '2026-10-23T12:00:00Z', 'seats': ['D-1-1', 'D-1-2']}
        invalid = dict(allocation, seats=['A-1-1', 'A-1-2'])
        self.assertEqual(self.finish('RESERVED', invalid).status_code, 409)
        self.assertEqual(self.store.read()['requests'][self.rid]['status'], 'ADMITTED')
        self.assertEqual(self.finish('RESERVED', allocation).status_code, 200)
        self.assertEqual(self.finish('RESERVED', allocation).status_code, 200)
        self.assertEqual(self.finish('RESERVED', dict(allocation, hold_id=str(uuid4()))).status_code, 409)

    def test_expired_payment_allows_one_new_attempt(self):
        allocation = {'hold_id': str(uuid4()), 'hold_status': 'ACTIVE',
                      'hold_expiry': '2026-10-23T12:00:00Z', 'seats': ['D-1-1', 'D-1-2']}
        self.assertEqual(self.finish('RESERVED', allocation).status_code, 200)
        self.network.request.return_value.status_code = 200
        self.network.request.return_value.json.return_value = {
            'request_id':self.rid, 'hold_id':allocation['hold_id'],
            'booking_status':'active', 'source':'seat-store', 'cached':False}
        self.assertEqual(self.client.post(self.path + '/rejoin').status_code, 409)
        self.network.request.return_value.json.return_value['booking_status'] = 'expired'
        self.assertEqual(self.client.get(self.path + '/checkout').status_code, 200)
        first = self.client.post(self.path + '/rejoin')
        self.assertEqual(first.status_code, 201)
        calls = self.network.request.call_count
        self.assertEqual(self.client.post(self.path + '/rejoin').json, first.json)
        self.assertEqual(self.network.request.call_count, calls)

    def test_cancellation_passes_exact_hold_and_retry_key_to_payment(self):
        allocation = {'hold_id': str(uuid4()), 'hold_status':'ACTIVE',
                      'hold_expiry':'2026-10-23T12:00:00Z', 'seats':['D-1-1','D-1-2']}
        self.finish('RESERVED', allocation)
        self.network.request.return_value.status_code = 200
        self.network.request.return_value.json.return_value = {'booking_status':'cancelled'}
        for _ in range(2):
            self.assertEqual(self.client.post(self.path + '/cancel', json={'action_key':'retry-me'}).status_code, 200)
            kwargs = self.network.request.call_args.kwargs
            self.assertEqual(kwargs['json'], {'request_id':self.rid,
                'hold_id':allocation['hold_id'], 'action_key':'retry-me'})


if __name__ == '__main__':
    unittest.main()
