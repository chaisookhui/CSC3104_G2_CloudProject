import copy
import json
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('dispatcher_api', ROOT / 'app.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
from state_store import StateStore


def test_database(test):
    dsn = os.getenv('DISPATCHER_TEST_DATABASE_URL')
    if not dsn:
        test.temp = tempfile.TemporaryDirectory()
        test.addCleanup(test.temp.cleanup)
        return 'sqlite:///' + str(Path(test.temp.name) / 'dispatcher.db')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    if not conninfo_to_dict(dsn).get('dbname','').endswith('_test'):
        raise ValueError('Dispatcher tests require a dedicated database ending in _test')
    schema = 'dispatcher_' + uuid4().hex
    with psycopg.connect(dsn,autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    def clean():
        with psycopg.connect(dsn,autocommit=True) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    test.addCleanup(clean)
    parts = urlsplit(dsn)
    params = dict(parse_qsl(parts.query))
    params['options'] = params.get('options','') + ' -c search_path=' + schema
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(params,quote_via=quote),parts.fragment))


# This is a factory, not a pytest function.
test_database.__test__ = False


class StateHistoryTests(unittest.TestCase):
    def setUp(self):
        self.url = test_database(self)
        self.store = StateStore(self.url)

    def test_large_history_is_retained_without_copying_it_into_worker_progress(self):
        batch = {'batch_id':'large','state':'COMPLETED','evidence':'x'*200000}
        token,state = self.store.claim()
        state['history'].append(batch)
        self.store.save(token,state,release=True)
        self.assertEqual(StateStore(self.url).read()['history'],[batch])
        token,state = self.store.claim()
        self.assertEqual(state['history'],[])
        self.assertEqual(state['events'],{})
        with self.store.transaction() as run:
            raw = run('SELECT payload FROM dispatcher_state').fetchone()['payload']
        self.assertLess(len(raw),1000)
        self.store.save(token,state,release=True)
        self.assertEqual(self.store.read()['history'],[batch])

    def test_retried_append_is_idempotent_and_conflicting_append_rolls_back(self):
        batch = {'batch_id':'one','state':'COMPLETED'}
        token,state = self.store.claim()
        state['history']=[batch]
        self.store.save(token,state)
        state['history']=[batch]
        self.store.save(token,state)
        self.assertEqual(self.store.read()['history'],[batch])
        state['history']=[dict(batch,state='CONFLICT')]
        with self.assertRaises(ValueError): self.store.save(token,state)
        self.assertEqual(self.store.read()['history'],[batch])

    def test_expired_writer_cannot_append_history(self):
        token,state = self.store.claim()
        state['history']=[{'batch_id':'stale','state':'COMPLETED'}]
        with self.store.transaction() as run:run('UPDATE dispatcher_state SET lease_until=0')
        with self.assertRaises(RuntimeError):self.store.save(token,state)
        self.assertEqual(self.store.read()['history'],[])

    def test_legacy_migration_preserves_order_receipts_active_batch_and_lease(self):
        batches=[{'batch_id':name,'state':'COMPLETED'} for name in ('first','second')]
        event={'event_id':'receipt','batch_id':'first','type':'batch.allocation_completed'}
        legacy={'active':{'batch_id':'running','state':'WAITING_FOR_ALLOCATION'},
                'history':batches,'events':{'receipt':event}}
        with self.store.transaction() as run:
            run('UPDATE dispatcher_state SET payload=?,token=?,lease_until=?',
                (json.dumps(legacy),'existing-owner',9999999999))
        restarted=StateStore(self.url)
        self.assertEqual(restarted.read(),legacy)
        with restarted.transaction() as run:
            row=run('SELECT payload,token,lease_until FROM dispatcher_state').fetchone()
        self.assertEqual(row['token'],'existing-owner')
        self.assertEqual(row['lease_until'],9999999999)
        self.assertEqual(json.loads(row['payload'])['history'],[])
        # An old writer's repeated inline snapshot does not duplicate migrated rows.
        later=copy.deepcopy(legacy)
        later['history'].append({'batch_id':'third','state':'COMPLETED'})
        with restarted.transaction() as run:
            run('UPDATE dispatcher_state SET payload=?',(json.dumps(later),))
        self.assertEqual(restarted.read(),later)
        restarted.record_event(event)
        with self.assertRaises(ValueError):restarted.record_event(dict(event,type='conflict'))


class WorkerSchedulingTests(unittest.TestCase):
    def test_progress_avoids_idle_wait_without_bypassing_dependency_backoff(self):
        dispatcher = Mock()
        dispatcher.tick.side_effect = [
            ({'state':'COMPLETED'}, 202),
            ({'state':'WAITING_FOR_ALLOCATION'}, 202),
            ({'state':'WAITING_FOR_ALLOCATION', 'retry_after_seconds':.75}, 202),
            ({'error':'Dependency handoff pending recovery'}, 503),
            ({'message':'No eligible queued requests'}, 200)]
        delays = []
        stop = Mock()
        stop.is_set.side_effect = lambda: len(delays) == 5
        stop.wait.side_effect = delays.append
        api.run_worker(dispatcher, stop)
        self.assertEqual(delays, [0, .1, .75, 1, 1])


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
        if url.endswith('/queue/activity'):
            return Response({'sale_state':'sale_started',
                             'queued_count':sum(r['status']=='QUEUED' for r in self.queue)})
        if url.endswith('/queue'):
            return Response({'sale_state': 'sale_started', 'requests': copy.deepcopy(self.queue)})
        if '/queue/next/' in url:
            limit = int(url.rsplit('/',1)[1])
            return Response({'sale_state':'sale_started', 'requests':copy.deepcopy(
                [r for r in self.queue if r['status']=='QUEUED'][:limit])})
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
    def test_idle_ticks_do_not_fetch_retained_customer_history(self):
        worker=api.Dispatcher(self.store,self.network)
        for activity in ({'sale_state':'pre_sale','queued_count':0},
                         {'sale_state':'sale_started','queued_count':0}):
            with patch.object(worker,'call',return_value=activity) as call:
                body,code=worker.tick()
                self.assertEqual(code,200)
                call.assert_called_once_with('GET',worker.waiting+'/queue/activity')

    def setUp(self):
        self.url = test_database(self)
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
