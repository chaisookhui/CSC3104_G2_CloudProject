import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_concurrent_rejoin_creates_one_successor_at_back(self):
        self.assertEqual(self.finish().status_code, 200)
        later = self.client.post('/submit', json={'user_id': 'later', 'section': 'A', 'party_size': 1}).json

        def rejoin(_):
            with self.app.test_client() as client:
                return client.post(self.path + '/rejoin', json={'user_id': 'u'})

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(rejoin, range(16)))
        self.assertEqual(sum(r.status_code == 201 for r in responses), 1)
        self.assertEqual(len({r.json['request_id'] for r in responses}), 1)
        self.assertGreater(responses[0].json['queue_number'], later['queue_number'])
        self.assertEqual(self.client.post(self.path + '/rejoin', json={'user_id': 'u', 'section': 'B'}).status_code, 409)
        self.assertEqual(self.client.post(self.path + '/rejoin', json={'user_id': 'someone-else'}).status_code, 404)

    def test_inflight_cannot_rejoin(self):
        self.assertEqual(self.client.post(self.path + '/rejoin', json={'user_id': 'u'}).status_code, 409)

    def test_invalid_or_conflicting_checkout_identity_cannot_change_outcome(self):
        allocation = {'hold_id': str(uuid4()), 'hold_status': 'ACTIVE',
                      'hold_expiry': '2026-10-23T12:00:00Z', 'seats': ['D-1-1', 'D-1-2']}
        invalid = dict(allocation, seats=['A-1-1', 'A-1-2'])
        self.assertEqual(self.finish('RESERVED', invalid).status_code, 409)
        self.assertEqual(self.store.read()['requests'][self.rid]['status'], 'ADMITTED')
        self.assertEqual(self.finish('RESERVED', allocation).status_code, 200)
        self.assertEqual(self.finish('RESERVED', allocation).status_code, 200)
        self.assertEqual(self.finish('RESERVED', dict(allocation, hold_id=str(uuid4()))).status_code, 409)

    def test_cached_payment_state_cannot_authorize_rejoin(self):
        allocation = {'hold_id': str(uuid4()), 'hold_status': 'ACTIVE',
                      'hold_expiry': '2026-10-23T12:00:00Z', 'seats': ['D-1-1', 'D-1-2']}
        self.finish('RESERVED', allocation)
        self.network.request.return_value.status_code = 200
        self.network.request.return_value.json.return_value = {
            'request_id': self.rid, 'hold_id': allocation['hold_id'],
            'booking_status': 'expired', 'source': 'cached'}
        self.assertEqual(self.client.post(self.path + '/rejoin', json={'user_id': 'u'}).status_code, 503)
        self.assertNotIn('rejoin_request_id', self.store.read()['requests'][self.rid])


if __name__ == '__main__':
    unittest.main()
