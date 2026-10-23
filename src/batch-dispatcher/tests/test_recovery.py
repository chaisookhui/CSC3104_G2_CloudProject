import copy
import importlib.util
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('dispatcher_api', ROOT / 'app.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
from state_store import StateStore


class Response:
    def __init__(self, data, code=200):
        self.data, self.status_code = data, code
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError('simulated dependency failure')
    def json(self):
        return self.data


class Network:
    def __init__(self):
        self.queue = []
        self.batch = None
        self.claims, self.submissions, self.syncs = [], [], []
        self.lose = None
        self.complete = False

    def append(self, rid='r1'):
        self.queue.append({'request_id': rid, 'queue_number': len(self.queue) + 1,
                           'section': 'D', 'party_size': 1, 'status': 'QUEUED'})

    def request(self, method, url, json=None, **kwargs):
        if url.endswith('/queue'):
            return Response({'sale_state': 'sale_started', 'requests': copy.deepcopy(self.queue)})
        if url.endswith('/queue/claim'):
            self.claims.append(copy.deepcopy(json))
            for r in self.queue:
                if r['request_id'] in json['request_ids']:
                    r['status'] = 'ADMITTED'
            result, stage = {'batch_id': json['batch_id']}, 'claim'
        elif method == 'POST' and url.endswith('/batches'):
            self.submissions.append(copy.deepcopy(json))
            if self.batch is not None:
                assert self.batch == json
            self.batch = copy.deepcopy(json)
            result, stage = {'batch_id': json['batch_id']}, 'submit'
        elif url.endswith('/queue/outcomes'):
            self.syncs.append(copy.deepcopy(json))
            for r in self.queue:
                if r['request_id'] in {o['request_id'] for o in json['outcomes']}:
                    r['status'] = 'UNAVAILABLE'
            result, stage = {'batch_id': json['batch_id']}, 'sync'
        else:
            return Response({'batch_id': self.batch['batch_id'], 'complete': self.complete,
                             'jobs': [{'request_id': r['request_id'], 'state': 'UNAVAILABLE'}
                                      for r in self.batch['requests']]})
        if self.lose == stage:
            self.lose = None
            raise requests.Timeout('Committed but response lost')
        return Response(result)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = 'sqlite:///' + str(Path(self.temp.name) / 'dispatcher.db')
        self.store = StateStore(self.url)
        self.network = Network()

    def resume(self):
        store = StateStore(self.url)
        with store.transaction() as run:
            # Advance the retry clock without sleeping in tests.
            import json
            row = run('SELECT payload FROM dispatcher_state').fetchone()
            state = json.loads(row['payload'])
            if state['active']:
                state['active']['retry_at'] = 0
            run('UPDATE dispatcher_state SET payload=?,lease_until=0', (json.dumps(state),))
        return api.Dispatcher(store, self.network)

    def test_restart_retries_original_identity_after_each_lost_response(self):
        for stage in ('claim', 'submit', 'sync'):
            with self.subTest(stage=stage):
                self.setUp()
                self.network.append()
                self.network.complete = True
                self.network.lose = stage
                first = api.Dispatcher(self.store, self.network)
                self.assertEqual(first.tick()[1], 503)
                batch_id = self.store.read()['active']['batch_id']
                self.resume().tick()
                state = self.store.read()
                self.assertIsNone(state['active'])
                self.assertEqual(state['history'][0]['batch_id'], batch_id)
                for calls in (self.network.claims, self.network.submissions, self.network.syncs):
                    self.assertTrue(all(c['batch_id'] == batch_id for c in calls))
                    self.assertTrue(all(c == calls[0] for c in calls))

    def test_empty_queue_then_late_arrival_and_no_callback(self):
        worker = api.Dispatcher(self.store, self.network)
        self.assertEqual(worker.tick()[1], 200)
        self.network.append()
        worker.tick()
        first_id = self.store.read()['active']['batch_id']
        self.network.complete = True
        self.resume().tick()
        self.assertIsNone(self.store.read()['active'])
        self.network.append('late')
        self.network.batch = None
        self.resume().tick()
        self.assertEqual(len(self.store.read()['history']), 2)
        self.assertNotEqual(self.store.read()['history'][1]['batch_id'], first_id)

    def test_durable_receipts_survive_concurrent_progress_and_restart(self):
        self.network.append()
        api.Dispatcher(self.store, self.network).tick()
        event = {'event_id': str(uuid4()), 'type': 'batch.allocation_completed',
                 'batch_id': self.store.read()['active']['batch_id'], 'total_requests': 1,
                 'outcomes': {'RESERVED': 0, 'UNAVAILABLE': 1, 'CANCELLED': 0}}
        token, stale = self.store.claim()
        client = api.create_app(StateStore(self.url), self.network).test_client()
        self.assertEqual(client.post('/allocator/status', json=event).status_code, 200)
        self.store.save(token, stale, release=True)
        restarted = api.create_app(StateStore(self.url), self.network).test_client()
        self.assertEqual(restarted.post('/allocator/status', json=event).status_code, 200)
        changed = dict(event, total_requests=2)
        self.assertEqual(restarted.post('/allocator/status', json=changed).status_code, 409)
        self.assertEqual(self.store.read()['events'][event['event_id']], event)

    def test_expired_worker_cannot_overwrite_replacement(self):
        token, state = self.store.claim()
        with self.store.transaction() as run:
            run('UPDATE dispatcher_state SET lease_until=0')
        replacement, current = self.store.claim()
        with self.assertRaises(RuntimeError):
            self.store.save(token, state)
        self.store.save(replacement, current, release=True)

    def test_only_one_replica_can_claim(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: StateStore(self.url).claim(), range(8)))
        self.assertEqual(sum(c is not None for c in claims), 1)


if __name__ == '__main__':
    unittest.main()
