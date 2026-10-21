import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from queue_store import MemoryStore


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.app = create_app(self.store)
        self.client = self.app.test_client()

    def submit(self, i):
        with self.app.test_client() as client:
            return client.post('/submit', json={
                'user_id': str(i), 'section': 'ABCD'[i % 4], 'party_size': i % 4 + 1})

    def test_global_lottery_then_concurrent_fcfs(self):
        early = [self.submit(i).json for i in range(12)]
        self.assertTrue(all(r['queue_number'] is None for r in early))
        with patch('app.random.SystemRandom.shuffle', side_effect=lambda ids: ids.reverse()) as shuffle:
            self.client.post('/sale/start')
            assigned = [self.client.get('/requests/' + r['request_id']).json for r in early]
            self.assertEqual([r['queue_number'] for r in assigned], list(range(12, 0, -1)))
            self.assertEqual([r['timestamp'] for r in assigned], [r['timestamp'] for r in early])
            self.client.post('/sale/start')
            shuffle.assert_called_once()
        with ThreadPoolExecutor(max_workers=20) as pool:
            late = [r.json for r in pool.map(self.submit, range(12, 112))]
        self.assertEqual(sorted(r['queue_number'] for r in late), list(range(13, 113)))
        self.assertTrue(all(r['entry_type'] == 'latecomer' for r in late))
        for party in early + assigned + late:
            self.assertNotIn('batch_order', party)
            self.assertNotIn('global_position', party)
        self.assertEqual(self.client.get('/status').json['queued_count'], 112)

    def test_duplicate_registration_and_validation(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            responses = list(pool.map(lambda _: self.submit(1), range(30)))
        self.assertEqual(sum(r.status_code == 201 for r in responses), 1)
        self.assertEqual(len({r.json['request_id'] for r in responses}), 1)
        self.assertEqual(self.client.post('/submit', json={'user_id': 'bad', 'section': [], 'party_size': 2}).status_code, 400)

    def test_dispatcher_endpoints_are_not_exposed(self):
        self.assertEqual(self.client.post('/batches/claim', json={'batch_id': 'b1'}).status_code, 404)
        self.assertEqual(self.client.post('/batches/b1/complete', json={'results': []}).status_code, 404)
        status = self.client.get('/status').json
        self.assertNotIn('active_batch', status)
        self.assertEqual(status['admission_policy'], 'external_dispatcher')

    def test_cutoff_concurrency_and_multiple_frontends(self):
        second = create_app(self.store)
        self.submit(0)
        def operation(i):
            if i == 20:
                with second.test_client() as client:
                    return client.post('/sale/start')
            return self.submit(i)
        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(operation, range(1, 101)))
        state = self.store.read()
        positions = [state['requests'][rid]['queue_number'] for rid in state['queue']]
        self.assertEqual(positions, list(range(1, 101)))
        seen_late = False
        for rid in state['queue']:
            party = state['requests'][rid]
            if party['entry_type'] == 'latecomer':
                seen_late = True
            else:
                self.assertFalse(seen_late)
        with second.test_client() as client:
            self.assertEqual(client.get('/status').json['queued_count'], 100)


if __name__ == '__main__':
    unittest.main()
