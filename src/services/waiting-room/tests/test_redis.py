"""Run with TEST_REDIS_URL for a real Redis server, otherwise fakeredis[lua]."""
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from queue_store import RedisStore


class RedisCorrectnessTests(unittest.TestCase):
    def setUp(self):
        self.namespace = 'test:waiting:' + str(uuid4())
        self.store = RedisStore(os.getenv('TEST_REDIS_URL', 'redis://localhost:6379/15'), self.namespace)
        if not os.getenv('TEST_REDIS_URL'):
            try:
                import fakeredis
                self.store.client = fakeredis.FakeRedis(decode_responses=True)
            except ImportError:
                self.skipTest('Set TEST_REDIS_URL or install fakeredis[lua]')
            self.store._register = self.store.client.register_script(self.store.REGISTER)
            self.store._open = self.store.client.register_script(self.store.OPEN)
        self.app = create_app(self.store)
        trigger = patch('app.requests.post')
        trigger.start().return_value.json.return_value = {}
        self.addCleanup(trigger.stop)
        self.addCleanup(lambda: self.store.client.delete(*self.store.keys))

    def submit(self, user):
        with self.app.test_client() as c:
            response = c.post('/submit', json={'user_id': str(user), 'section': 'A', 'party_size': 1})
            self.assertIn(response.status_code, (200, 201), response.json)
            return response.status_code, response.json

    def test_simultaneous_duplicates_and_latecomers(self):
        self.store.open_sale()
        with ThreadPoolExecutor(max_workers=16) as pool:
            duplicates = list(pool.map(self.submit, ['same'] * 50))
            late = list(pool.map(self.submit, range(100)))
        self.assertEqual(sum(code == 201 for code, _ in duplicates), 1)
        self.assertEqual(len({p['request_id'] for _, p in duplicates}), 1)
        self.assertEqual(sorted(p['queue_number'] for _, p in late), list(range(2, 102)))
        self.assertEqual(self.store.read()['next_number'], 102)

    def test_opening_cutoff_and_recovery(self):
        early = [self.submit(i)[1]['request_id'] for i in range(17)]
        first = self.store.open_sale(batch_size=3)
        self.assertEqual(first['sale_state'], 'opening')
        with self.app.test_client() as c:
            self.assertEqual(c.post('/queue/claim', json={'batch_id':'bad', 'request_ids':early[:1]}).status_code, 409)
        with ThreadPoolExecutor(max_workers=8) as pool:
            late = list(pool.map(self.submit, range(17, 37)))
        # A replacement API/store object sees all committed opening progress.
        replacement = RedisStore('redis://localhost', self.namespace)
        replacement.client = self.store.client
        replacement._open = replacement.client.register_script(replacement.OPEN)
        while replacement.open_sale(batch_size=3)['sale_state'] == 'opening':
            pass
        snapshot = self.store.read()
        self.assertEqual([snapshot['requests'][rid]['queue_number'] for rid in snapshot['queue']], list(range(1, 38)))
        self.assertEqual(set(snapshot['queue'][:17]), set(early))
        self.assertEqual(sorted(p['queue_number'] for _, p in late), list(range(18, 38)))
        self.store.open_sale()
        self.assertEqual(self.store.read(), snapshot)

    def test_concurrent_claim_and_idempotent_outcomes(self):
        for i in range(4):
            self.submit(i)
        self.store.open_sale()
        ids = self.store.read()['queue'][:2]
        def claim(batch):
            with self.app.test_client() as c:
                return batch, c.post('/queue/claim', json={'batch_id': batch, 'request_ids': ids}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ['one', 'two']))
        self.assertEqual(sorted(code for _, code in results), [200, 409])
        winner = next(batch for batch, code in results if code == 200)
        with self.app.test_client() as c:
            self.assertEqual(c.post('/queue/claim', json={'batch_id':winner,'request_ids':ids}).status_code, 200)
            payload = {'batch_id':winner, 'outcomes':[{'request_id':rid,'status':'UNAVAILABLE'} for rid in ids]}
            for _ in range(2):
                self.assertEqual(c.post('/queue/outcomes', json=payload).status_code, 200)
            before = self.store.read()
            payload['outcomes'][0]['status'] = 'RESERVED'
            self.assertEqual(c.post('/queue/outcomes', json=payload).status_code, 409)
            self.assertEqual(self.store.read(), before)


if __name__ == '__main__':
    unittest.main()
