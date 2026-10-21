"""Run with python -m unittest discover -s src/allocation/tests -v."""
import copy
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from src.allocation.algorithm import prepare_batch
from src.allocation.demo_dispatcher import sample_batch
from src.allocation.job_store import JobStore, Conflict
from src.allocation.worker import process_one
from src.allocation.seat_client import hold_seats, SeatStoreError
from src.allocation.app import create_app
from src.allocation.dispatcher_client import notify_one


def drain_claims(url, output, active_sections, guard):
    store = JobStore(url)
    while True:
        claim = store.claim()
        if claim is None:
            break
        section_index = ord(claim['job']['section']) - ord('A')
        with guard:
            if active_sections[section_index]:
                raise AssertionError('Two processes allocated in the same section concurrently')
            active_sections[section_index] += 1
        # Hold the simulated allocation open so other processes race for jobs.
        time.sleep(0.02)
        output.put(claim['job']['request_id'])
        with guard:
            active_sections[section_index] -= 1
        store.finish(claim, result={'state': 'UNAVAILABLE'})


class SchedulingTests(unittest.TestCase):
    def test_cycle_and_global_order(self):
        payload = sample_batch()
        payload['requests'].reverse()
        orders, jobs = prepare_batch(payload)
        self.assertEqual(orders['A'], [4, 2, 3, 1])
        a = [j for j in jobs if j['section'] == 'A']
        self.assertEqual([j['party_size'] for j in a], [4, 2, 3, 1, 4, 2, 3, 4, 2, 4])
        self.assertEqual([j['global_position'] for j in a if j['party_size'] == 4], [1, 2, 3, 4])
        self.assertEqual(prepare_batch(sample_batch('second', True))[0]['A'], [3, 4, 1, 2])

    def test_bad_snapshot_rejected(self):
        base = sample_batch()
        mutations = [lambda p: p['section_demand']['A'].update({'4': 9}),
                     lambda p: p['requests'][0].update({'party_size': True}),
                     lambda p: p['requests'][0].update({'global_position': 2}),
                     lambda p: p['requests'][0].update({'request_id': p['requests'][1]['request_id']})]
        for mutate in mutations:
            payload = copy.deepcopy(base)
            mutate(payload)
            with self.assertRaises(ValueError):
                prepare_batch(payload)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.url = 'sqlite:///' + str(Path(self.tmp.name) / 'jobs.sqlite3')
        self.store = JobStore(self.url)
        self.store.initialize()
        self.payload = sample_batch()
        orders, jobs = prepare_batch(self.payload)
        self.store.submit(self.payload, orders, jobs)

    def tearDown(self):
        self.tmp.cleanup()

    def test_section_rotation_and_concurrent_claims(self):
        first = self.store.claim()
        second = self.store.claim()
        self.assertIsNone(self.store.claim())  # A and B both have active parties
        self.store.finish(first, result={'state': 'UNAVAILABLE'})
        third = self.store.claim()
        self.assertEqual([c['job']['section'] for c in (first, second, third)], ['A', 'B', 'A'])
        self.assertEqual(len({c['job']['request_id'] for c in (first, second, third)}), 3)
        self.assertFalse(self.store.batch('demo-1')['complete'])

    def test_same_section_waits_until_outcome_is_saved(self):
        first = self.store.claim()
        other_section = self.store.claim()
        self.assertEqual(first['job']['party_size'], 4)
        self.assertEqual(other_section['job']['section'], 'B')
        self.assertIsNone(self.store.claim())
        self.store.finish(other_section, result={'state': 'UNAVAILABLE'})
        self.assertIsNone(self.store.claim())  # A still busy, B now empty
        self.store.finish(first, result={'state': 'RESERVED', 'hold_id': 'h'})
        next_party = self.store.claim()
        self.assertEqual(next_party['job']['section'], 'A')
        self.assertEqual(next_party['job']['party_size'], 2)

    def test_delayed_retry_blocks_its_section_only(self):
        with patch.object(self.store, '_now', return_value=100):
            first = self.store.claim()
            self.store.finish(first, error='uncertain response')
            other = self.store.claim()
            self.assertEqual(other['job']['section'], 'B')
            self.assertIsNone(self.store.claim())
        with patch.object(self.store, '_now', return_value=103):
            retry = self.store.claim()
            self.assertEqual(retry['job']['request_id'], first['job']['request_id'])
            self.assertIsNone(self.store.claim())

    def test_completion_only_after_entire_batch_and_retry_same_event(self):
        self.assertIsNone(self.store.claim_completion())
        process_one(self.store, hold=lambda *_: {'success': False})
        self.assertIsNone(self.store.claim_completion())
        while process_one(self.store, hold=lambda *_: {'success': False}):
            pass
        self.assertEqual(self.store.batch('demo-1')['completion_notification'], 'pending')
        self.assertFalse(notify_one(self.store, None))
        post = Mock(return_value=Mock(status_code=503))
        with patch.object(self.store, '_now', return_value=100):
            self.assertTrue(notify_one(self.store, 'http://dispatcher/completed', post))
        original = post.call_args.kwargs['json']
        self.assertEqual(original['total_requests'], 11)
        self.assertEqual(original['outcomes']['UNAVAILABLE'], 11)
        with patch.object(self.store, '_now', return_value=103):
            post.return_value.status_code = 204
            self.assertTrue(notify_one(self.store, 'http://dispatcher/completed', post))
            self.assertEqual(post.call_args.kwargs['json'], original)
            self.assertEqual(post.call_args.kwargs['headers']['Idempotency-Key'], original['event_id'])
        self.assertEqual(self.store.batch('demo-1')['completion_notification'], 'delivered')
        self.assertIsNone(self.store.claim_completion())
        self.assertFalse(notify_one(self.store, 'http://dispatcher/completed', post))
        self.assertEqual(post.call_count, 2)

    def test_initialize_upgrades_existing_queue_without_duplicate_events(self):
        self.store.initialize()
        self.assertFalse(self.store.batch('demo-1')['complete'])
        self.assertIsNone(self.store.claim_completion())
        while process_one(self.store, hold=lambda *_: {'success': False}):
            pass
        # Simulate a database that completed allocation before outbox support.
        with self.store.transaction() as execute:
            execute("DELETE FROM allocation_completions")
        self.store.initialize()
        self.store.initialize()
        event = self.store.claim_completion()
        self.assertEqual(event['payload']['batch_id'], 'demo-1')
        self.assertIsNone(self.store.claim_completion())
        self.store.finish_completion(event)
        self.store.initialize()
        self.assertIsNone(self.store.claim_completion())

    def test_completion_claim_is_exclusive_and_recovers_after_crash(self):
        while process_one(self.store, hold=lambda *_: {'success': False}):
            pass
        with patch.object(self.store, '_now', return_value=100):
            old = self.store.claim_completion(lease_seconds=10)
            self.assertIsNone(self.store.claim_completion())
        with patch.object(self.store, '_now', return_value=111):
            new = self.store.claim_completion()
            self.assertEqual(old['payload'], new['payload'])
            self.assertFalse(self.store.finish_completion(old))
            self.assertTrue(self.store.finish_completion(new))
        # A duplicate completion attempt cannot generate another logical event.
        self.assertFalse(self.store.finish_completion(new))
        self.assertIsNone(self.store.claim_completion())

    def test_fixed_batch_gate_and_idempotent_submission(self):
        orders, jobs = prepare_batch(self.payload)
        self.assertFalse(self.store.submit(self.payload, orders, jobs))
        other = sample_batch('second', True)
        with self.assertRaises(Conflict):
            self.store.submit(other, *prepare_batch(other))
        while process_one(self.store, hold=lambda *_: {'success': False}):
            pass
        self.assertTrue(self.store.batch('demo-1')['complete'])
        self.assertTrue(self.store.submit(other, *prepare_batch(other)))
        self.assertFalse(self.store.batch('second')['complete'])

    def test_expired_claim_and_stale_ack(self):
        with patch.object(self.store, '_now', return_value=100):
            old = self.store.claim(lease_seconds=10)
        with patch.object(self.store, '_now', return_value=111):
            # Claim B first according to the shared section cursor, then retry A.
            self.store.claim()
            new = self.store.claim()
            self.assertEqual(old['job']['request_id'], new['job']['request_id'])
            self.assertNotEqual(old['token'], new['token'])
            self.assertFalse(self.store.finish(old, result={'state': 'UNAVAILABLE'}))
            self.assertTrue(self.store.finish(new, result={'state': 'RESERVED', 'hold_id': 'same-hold'}))

    def test_timeout_retries_same_request_and_blocks_completion(self):
        calls = []
        def timeout(*args):
            calls.append(args)
            raise SeatStoreError('response lost')
        with patch.object(self.store, '_now', return_value=100):
            process_one(self.store, hold=timeout)
        self.assertEqual(self.store.batch('demo-1')['jobs'][0]['state'], 'RETRY')
        with patch.object(self.store, '_now', return_value=110):
            process_one(self.store, hold=lambda *_: {'success': False})  # B
            process_one(self.store, hold=timeout)
        self.assertEqual(calls[0], calls[1])
        self.assertFalse(self.store.batch('demo-1')['complete'])

    def test_crash_after_hold_commit_reuses_the_same_hold(self):
        holds = {}
        def idempotent_hold(section, size, rid):
            return holds.setdefault(rid, {'success': True, 'hold_id': 'hold-' + rid,
                                         'hold_expiry': 'unchanged', 'seats': ['mock-seat'] * size})
        with patch.object(self.store, '_now', return_value=100):
            lost_claim = self.store.claim(lease_seconds=10)
            job = lost_claim['job']
            committed = idempotent_hold(job['section'], job['party_size'], job['request_id'])
            # Simulate death between SeatStore commit and queue acknowledgement.
        with patch.object(self.store, '_now', return_value=111):
            process_one(self.store, hold=lambda *_: {'success': False})  # B
            process_one(self.store, hold=idempotent_hold)  # redelivered A
        recovered = self.store.batch('demo-1')['jobs'][0]
        self.assertEqual(recovered['state'], 'RESERVED')
        self.assertEqual(recovered['result']['hold_id'], committed['hold_id'])
        self.assertEqual(recovered['result']['hold_expiry'], 'unchanged')
        self.assertEqual(len(holds), 1)

    def test_retry_limit_blocks_abandoned_claim(self):
        with patch.object(self.store, '_now', return_value=100):
            self.store.claim(lease_seconds=10, max_attempts=1)
        with patch.object(self.store, '_now', return_value=111):
            self.store.claim(max_attempts=1)
        self.assertEqual(self.store.batch('demo-1')['jobs'][0]['state'], 'BLOCKED')
        self.assertFalse(self.store.batch('demo-1')['complete'])

    def test_permanent_error_is_blocked_not_no_seats(self):
        def conflict(*_):
            raise SeatStoreError('HTTP 409', retryable=False)
        process_one(self.store, hold=conflict)
        state = self.store.batch('demo-1')
        self.assertEqual(state['jobs'][0]['state'], 'BLOCKED')
        self.assertFalse(state['complete'])

    def test_three_independent_processes_claim_each_job_once(self):
        ctx = multiprocessing.get_context('spawn')
        output = ctx.Queue()
        active_sections = ctx.Array('i', 4, lock=False)
        guard = ctx.Lock()
        processes = [ctx.Process(target=drain_claims, args=(self.url, output, active_sections, guard)) for _ in range(3)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            if process.is_alive():
                process.terminate()
                process.join()
                self.fail('Worker hung')
            self.assertEqual(process.exitcode, 0)
        ids = [output.get(timeout=2) for _ in self.payload['requests']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(self.store.batch('demo-1')['complete'])
        output.close()

    def test_api(self):
        client = create_app(self.store).test_client()
        self.assertEqual(client.post('/batches', json=self.payload).status_code, 200)
        self.assertEqual(client.post('/batches', json=[]).status_code, 400)
        self.assertEqual(client.get('/batches/demo-1').status_code, 200)
        self.assertEqual(client.get('/batches/missing').status_code, 404)
        self.assertEqual(client.get('/ready').status_code, 200)
        bad = copy.deepcopy(self.payload)
        bad['section_demand']['A']['4'] = 9
        self.assertEqual(client.post('/batches', json=bad).status_code, 400)


class ClientTests(unittest.TestCase):
    @patch('src.allocation.seat_client.requests.post')
    def test_invalid_json_shape_and_http_errors(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = []
        with self.assertRaises(SeatStoreError):
            hold_seats('A', 2, 'r')
        post.return_value.status_code = 409
        with self.assertRaises(SeatStoreError) as caught:
            hold_seats('A', 2, 'r')
        self.assertFalse(caught.exception.retryable)
        post.return_value.status_code = 503
        with self.assertRaises(SeatStoreError) as caught:
            hold_seats('A', 2, 'r')
        self.assertTrue(caught.exception.retryable)

    @patch('src.allocation.seat_client.requests.post')
    def test_hold_metadata_preserved_and_adjacency_checked(self, post):
        data = {'success': True, 'request_id': 'r', 'hold_id': 'h', 'hold_status': 'ACTIVE',
                'hold_expiry': '2026-10-21T12:00:00Z', 'seats': [
                    {'seat_id': f'A-1-{i}', 'section': 'A', 'row': 1, 'position_in_row': i,
                     'state': 'HELD', 'held_by_request_id': 'r', 'hold_id': 'h'} for i in (1, 2)]}
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = data
        result = hold_seats('A', 2, 'r')
        self.assertEqual(result['hold_id'], 'h')
        self.assertEqual(result['seats'], ['A-1-1', 'A-1-2'])
        data['seats'][1]['position_in_row'] = 4
        with self.assertRaises(SeatStoreError):
            hold_seats('A', 2, 'r')


if __name__ == '__main__':
    unittest.main()
