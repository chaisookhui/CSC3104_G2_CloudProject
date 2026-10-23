"""Recoverable fixed-batch dispatcher; see README for API/worker startup."""
import logging
import os
import signal
import threading
import time
from pathlib import Path
from uuid import uuid4

import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from dispatcher_logic import BatchedRequest, parse_waiting_room_queue, send_allocation_input, build_allocator_payload
from state_store import StateStore


class Dispatcher:
    def __init__(self, store, session=None, batch_size=50):
        if not 1 <= batch_size <= 100:
            raise ValueError('BATCH_SIZE must be between 1 and 100')
        self.store, self.http, self.batch_size = store, session or requests, batch_size
        self.waiting = os.getenv('WAITING_ROOM_URL', 'http://127.0.0.1:5001').rstrip('/')
        self.allocator = os.getenv('ALLOCATOR_URL', 'http://127.0.0.1:5002').rstrip('/')

    def call(self, method, url, payload=None):
        response = self.http.request(method, url, json=payload, timeout=(3, 5), allow_redirects=False)
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            raise ValueError('Unexpected dependency HTTP status')
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('Expected dependency object')
        return data

    def tick(self):
        claim = self.store.claim()
        if claim is None:
            return {'message': 'Dispatcher already processing'}, 202
        token, state = claim
        try:
            active = state['active']
            if active and active.get('retry_at', 0) > time.time():
                return {'batch_id': active['batch_id'], 'state': active['state']}, 202
            if active is None:
                queue = self.call('GET', self.waiting + '/queue')
                if queue.get('sale_state') == 'pre_sale':
                    return {'message': 'Sale has not started'}, 200
                records = parse_waiting_room_queue(queue)[:self.batch_size]
                if not records:
                    return {'message': 'No eligible queued requests'}, 200
                batch_id = 'batch-' + str(uuid4())
                payload = send_allocation_input(batch_id, [BatchedRequest(
                    r.request_id, r.global_position, r.section, r.party_size, batch_id) for r in records])
                active = {'batch_id': batch_id, 'batch_size': len(records),
                          'allocator_input': build_allocator_payload(payload),
                          'state': 'CLAIMING', 'attempts': 0}
                state['active'] = active
                self.store.save(token, state)
            batch_id = active['batch_id']
            if active['state'] == 'CLAIMING':
                result = self.call('POST', self.waiting + '/queue/claim', {
                    'batch_id': batch_id,
                    'request_ids': [r['request_id'] for r in active['allocator_input']['requests']]})
                if result.get('batch_id') != batch_id:
                    raise ValueError('Wrong claim acknowledgement')
                active['state'] = 'SUBMITTING'
                self.store.save(token, state)
            if active['state'] == 'SUBMITTING':
                result = self.call('POST', self.allocator + '/batches', active['allocator_input'])
                if result.get('batch_id') != batch_id:
                    raise ValueError('Wrong allocator acknowledgement')
                active['state'] = 'WAITING_FOR_ALLOCATION'
                self.store.save(token, state)
            if active['state'] == 'WAITING_FOR_ALLOCATION':
                details = self.call('GET', self.allocator + '/batches/' + batch_id)
                if details.get('batch_id') != batch_id:
                    raise ValueError('Wrong allocator batch')
                if details.get('complete') is not True:
                    return {'batch_id': batch_id, 'state': active['state']}, 202
                jobs = details.get('jobs')
                expected = {r['request_id'] for r in active['allocator_input']['requests']}
                if (not isinstance(jobs, list) or any(not isinstance(j, dict) for j in jobs)
                        or len(jobs) != len(expected)
                        or {j.get('request_id') for j in jobs} != expected
                        or any(j.get('state') not in ('RESERVED', 'UNAVAILABLE') for j in jobs)):
                    raise ValueError('Mismatched or unsupported allocator outcomes')
                outcomes = []
                for job in jobs:
                    outcome = {'request_id': job['request_id'], 'status': job['state']}
                    if job['state'] == 'RESERVED':
                        result = job.get('result')
                        if not isinstance(result, dict) or not result.get('hold_id'):
                            raise ValueError('Reserved outcome missing checkout identity')
                        outcome['allocation'] = {k: result.get(k) for k in (
                            'hold_id', 'hold_status', 'hold_expiry', 'seats')}
                    outcomes.append(outcome)
                active['outcomes'] = outcomes
                active['state'] = 'SYNCING_OUTCOMES'
                self.store.save(token, state)
            if active['state'] == 'SYNCING_OUTCOMES':
                result = self.call('POST', self.waiting + '/queue/outcomes',
                                   {'batch_id': batch_id, 'outcomes': active['outcomes']})
                if result.get('batch_id') != batch_id:
                    raise ValueError('Wrong outcome acknowledgement')
                active['state'] = 'COMPLETED'
                active.pop('last_error', None)
                state['history'].append(active)
                state['active'] = None
            return {'batch_id': batch_id, 'state': active['state']}, 202
        except (requests.RequestException, ValueError) as exc:
            active = state['active']
            if active:
                active['attempts'] += 1
                active['last_error'] = type(exc).__name__
                active['retry_at'] = time.time() + min(30, 2 ** min(active['attempts'], 5))
            return {'error': 'Dependency handoff pending recovery',
                    'batch_id': active['batch_id'] if active else None}, 503
        finally:
            self.store.save(token, state, release=True)


def create_app(store=None, session=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 128 * 1024
    default = 'sqlite:///' + str(Path(__file__).resolve().parents[2] / '.local' / 'dispatcher.sqlite3')
    store = store or StateStore(os.getenv('DISPATCHER_DATABASE_URL', default))
    dispatcher = Dispatcher(store, session, int(os.getenv('BATCH_SIZE', '50')))
    app.extensions['dispatcher'] = dispatcher

    @app.post('/batches/next')
    def next_batch():
        body, code = dispatcher.tick()
        return jsonify(body), code

    @app.post('/allocator/status')
    def completion():
        event = request.get_json(silent=True)
        if (not isinstance(event, dict) or event.get('type') != 'batch.allocation_completed'
                or any(not isinstance(event.get(k), str) or not event[k] or len(event[k]) > 128
                       for k in ('event_id', 'batch_id'))
                or type(event.get('total_requests')) is not int
                or not isinstance(event.get('outcomes'), dict)):
            return jsonify(error='Invalid completion event'), 400
        try:
            store.record_event(event)
        except ValueError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(message='Completion receipt persisted; worker verifies allocator state'), 200

    @app.get('/health')
    def health():
        return jsonify(status='ok', service='batch-dispatcher')

    @app.get('/ready')
    @app.get('/status')
    def status():
        state = store.read()
        active = state['active']
        return jsonify(active_batch_id=active['batch_id'] if active else None,
                       batch_state=active['state'] if active else 'IDLE',
                       current=active, batch_history=state['history'], batch_size=dispatcher.batch_size)

    @app.get('/batches/current')
    def current():
        return jsonify(store.read()['active'] or {'message': 'No active batch'})

    @app.get('/batches/allocator-input')
    def allocator_input():
        active = store.read()['active']
        return (jsonify(active['allocator_input']), 200) if active else (jsonify(error='No active batch'), 404)

    @app.get('/batches/history')
    def history():
        state = store.read()
        return jsonify(history=state['history'], total_batches=len(state['history']))

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        app.logger.exception('Dispatcher operation failed')
        return jsonify(error='Dispatcher storage/recovery unavailable'), 503

    return app


def run_worker(dispatcher, stop):
    while not stop.is_set():
        try:
            dispatcher.tick()
        except Exception:
            logging.exception('Recovery tick failed; durable work retained')
        stop.wait(1)


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    application = create_app()
    stop = threading.Event()
    if len(sys.argv) > 1 and sys.argv[1] == 'worker':
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        run_worker(application.extensions['dispatcher'], stop)
    else:
        thread = threading.Thread(target=run_worker, args=(application.extensions['dispatcher'], stop), daemon=True)
        thread.start()
        try:
            application.run(host=os.getenv('DISPATCHER_HOST', '127.0.0.1'),
                            port=int(os.getenv('DISPATCHER_PORT', '5005')), debug=False, use_reloader=False)
        finally:
            stop.set()
            thread.join(timeout=45)
