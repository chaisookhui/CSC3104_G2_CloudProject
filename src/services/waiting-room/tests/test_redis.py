"""Run with TEST_REDIS_URL for a real Redis server, otherwise fakeredis[lua]."""
import os
import json
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
    def test_scoped_claim_commutes_with_a_new_registration(self):
        self.store.open_sale()
        first = self.submit('first')[1]['request_id']
        snapshot = self.store._batch_snapshot
        late = []
        def race(*args):
            result = snapshot(*args)
            if not late: late.append(self.submit('late')[1]['request_id'])
            return result
        with patch.object(self.store,'_batch_snapshot',side_effect=race) as observed:
            with self.app.test_client() as client:
                self.assertEqual(client.post('/queue/claim',json={
                    'batch_id':'scoped-race','request_ids':[first]}).status_code,200)
            self.assertEqual(observed.call_count,1)
        self.assertEqual([p['request_id'] for p in self.store.next_queued(10)['requests']],late)
        self.assertEqual(self.store.activity()['queued_count'],1)
        self.assertEqual(self.store.read()['next_number'],3)

    def test_bounded_batch_paths_preserve_global_order_and_whole_batch_validation(self):
        for i in range(30): self.submit(i)
        self.store.open_sale()
        ordered = self.store.read()['queue']
        # Normal hot paths must not fetch the full historical Python snapshot.
        with patch.object(self.store, '_read', side_effect=AssertionError('Full history read')):
            with self.app.test_client() as client:
                page = client.get('/queue/next/3').json
                self.assertEqual([p['request_id'] for p in page['requests']], ordered[:3])
                wrong = {'batch_id':'bounded','request_ids':ordered[1:4]}
                self.assertEqual(client.post('/queue/claim', json=wrong).status_code,409)
                correct = {'batch_id':'bounded','request_ids':ordered[:3]}
                self.assertEqual(client.post('/queue/claim', json=correct).status_code,200)
                self.assertEqual(client.post('/queue/claim', json=correct).status_code,200)
                partial = {'batch_id':'bounded','outcomes':[
                    {'request_id':rid,'status':'UNAVAILABLE'} for rid in ordered[:2]]}
                self.assertEqual(client.post('/queue/outcomes',json=partial).status_code,409)
                full = {'batch_id':'bounded','outcomes':[
                    {'request_id':rid,'status':'UNAVAILABLE'} for rid in ordered[:3]]}
                self.assertEqual(client.post('/queue/outcomes',json=full).status_code,200)
                self.assertEqual(client.post('/queue/outcomes',json=full).status_code,200)
                page = client.get('/queue/next/3').json
                self.assertEqual([p['request_id'] for p in page['requests']],ordered[3:6])
        self.assertEqual(self.store.activity()['queued_count'],27)
        self.assertEqual(len(self.store.read()['requests']),30)

    def test_older_registration_cannot_be_hidden_by_a_new_indexed_registration(self):
        self.store.open_sale()
        first = self.submit('first')[1]['request_id']
        self.store.activity()
        party = dict(self.store.get_request(first), request_id='old-rid',user_id='old-user',queue_number=2)
        # Simulate the previous registration Lua: both revisions, no new index.
        with self.store.client.pipeline() as pipe:
            pipe.hset(self.store.keys[1],'old-user','old-rid')
            pipe.hset(self.store.keys[2],'old-rid',json.dumps(party))
            pipe.zadd(self.store.keys[3],{'old-rid':2})
            pipe.hincrby(self.store.keys[0],'next_number',1)
            pipe.hincrby(self.store.keys[0],'queued_count',1)
            pipe.incr(self.store.keys[5]);pipe.incr(self.store.keys[6]);pipe.execute()
        newest = self.submit('new')[1]['request_id']
        self.assertEqual([p['request_id'] for p in self.store.next_queued(10)['requests']],
                         [first,'old-rid',newest])
        self.assertEqual(self.store.activity()['queued_count'],3)

    def test_previous_transition_marker_does_not_validate_stale_queue_index(self):
        rid = self.submit('first')[1]['request_id']
        self.store.open_sale();self.store.activity()
        party = dict(self.store.get_request(rid),status='ADMITTED',batch_id='old')
        with self.store.client.pipeline() as pipe:
            pipe.hset(self.store.keys[2],rid,json.dumps(party))
            pipe.incr(self.store.keys[5]);pipe.execute()
        logical = int(self.store.client.get(self.store.keys[5]))-int(self.store.client.get(self.store.keys[6]))
        self.store.client.hset(self.store.keys[0],mapping={'activity_revision':logical,'queued_count':0})
        self.assertEqual(self.store.next_queued(10)['requests'],[])
        with self.app.test_client() as client:
            self.assertEqual(client.post('/queue/outcomes',json={'batch_id':'old',
                'outcomes':[{'request_id':rid,'status':'UNAVAILABLE'}]}).status_code,200)

    def test_pre_sale_claim_returns_original_rejection(self):
        first = self.submit('first')[1]['request_id']
        with self.app.test_client() as client:
            self.assertEqual(client.post('/queue/claim', json={'batch_id':'early','request_ids':[first]}).status_code, 409)

    def test_batch_transition_commutes_with_registration_without_losing_counter(self):
        first = self.submit('first')[1]['request_id']
        self.store.open_sale()
        calls = []
        def transition(state):
            calls.append(1)
            # Deterministically inject a committed registration after snapshot.
            self.submit('concurrent')
            state['requests'][first].update(status='ADMITTED', batch_id='batch')
        self.store.update(transition, append_safe=True)
        self.assertEqual(len(calls), 1)
        state = self.store.read()
        self.assertEqual(len(state['requests']), 2)
        self.assertEqual([state['requests'][r]['queue_number'] for r in state['queue']], [1, 2])
        self.assertEqual(self.store.activity()['queued_count'], 1)

    def test_legacy_writer_invalidates_transition_and_heals_activity_counter(self):
        first = self.submit('first')[1]['request_id']
        self.store.open_sale()
        self.store.activity()
        calls = []
        def transition(state):
            calls.append(1)
            if len(calls) == 1:
                # Old code writes records and global revision, without new metadata.
                party = dict(state['requests'][first], status='ADMITTED', batch_id='old')
                with self.store.client.pipeline() as pipe:
                    import json
                    pipe.hset(self.store.keys[2], first, json.dumps(party))
                    pipe.incr(self.store.keys[5]); pipe.execute()
            return state['requests'][first]['status']
        self.assertEqual(self.store.update(transition, append_safe=True), 'ADMITTED')
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.store.activity()['queued_count'], 0)

    def test_append_safe_path_rejects_structural_mutation(self):
        self.store.open_sale()
        with self.assertRaises(ValueError):
            self.store.update(lambda state: state.update(next_number=99), append_safe=True)
        self.assertEqual(self.store.read()['next_number'], 1)

    def test_activity_counter_survives_opening_latecomers_and_idempotent_claims(self):
        for i in range(7): self.submit(i)
        self.assertEqual(self.store.activity(), {'sale_state':'pre_sale','queued_count':0})
        self.store.open_sale(batch_size=2)
        self.submit('late')
        with self.app.test_client() as client:
            # During OPENING only part of the initial lottery has been numbered.
            # A rejected claim must not replace the total with that partial count.
            ids=self.store.read()['queue'][:1]
            self.assertEqual(client.post('/queue/claim',json={'batch_id':'too-early','request_ids':ids}).status_code,409)
        self.assertEqual(self.store.client.hget(self.store.keys[0],'queued_count'),'8')
        while self.store.open_sale(batch_size=2)['sale_state']=='opening': pass
        self.assertEqual(self.store.activity()['queued_count'],8)
        ids=self.store.read()['queue'][:3]
        with self.app.test_client() as client:
            for _ in range(2):
                self.assertEqual(client.post('/queue/claim',json={'batch_id':'activity','request_ids':ids}).status_code,200)
                self.assertEqual(self.store.activity()['queued_count'],5)
        # Older namespaces remain readable, with no false zero-backlog claim.
        self.store.client.hdel(self.store.keys[0],'queued_count')
        self.assertEqual(self.store.activity()['queued_count'],5)
        self.store.update(lambda state: None)
        self.assertEqual(self.store.client.hget(self.store.keys[0],'queued_count'),'5')

    def test_replay_fixture_is_lab_only_and_reproduces_queue_numbers(self):
        parties = {str(i): self.submit(i)[1] for i in range(4)}
        order = ['2','0','3','1']
        with patch.dict(os.environ, {'EXPERIMENT_NAMESPACE':'csc3104'}):
            with self.assertRaises(RuntimeError): self.store.prepare_replay(order)
        with patch.dict(os.environ, {'EXPERIMENT_NAMESPACE':'csc3104-lab'}):
            with self.assertRaises(ValueError): self.store.prepare_replay(['0','0'])
            self.assertEqual(self.store.prepare_replay(order),4)
            self.store.open_sale()
            actual = [self.store.get_request(parties[user]['request_id']) for user in order]
            self.assertEqual([party['queue_number'] for party in actual],[1,2,3,4])
            self.assertTrue(all(party['eligible_at'] > 0 for party in actual))
            with self.assertRaises(Exception): self.store.prepare_replay(order)

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
