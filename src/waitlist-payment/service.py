"""Payment API and separate durable recovery worker; no seat-store imports."""
import argparse
import hmac
import logging
import signal
import threading
from datetime import datetime
from uuid import UUID

import psycopg
import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from payment_db import Database
from payment_settings import settings
from lifecycle import Conflict, DependencyError, Lifecycle, NotFound, SeatClient


def serializable(value):
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict):
        return {k: serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    return value


def create_app(lifecycle=None, api_token=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
    if lifecycle is None:
        config = settings()
        lifecycle = Lifecycle(Database(config['database_url']),
            SeatClient(config['seat_url'], config['timeout'], config['cancel_path']), config['status_url'])
        if api_token is None:
            api_token = config['api_token']
    api_token = api_token or ''
    app.extensions['lifecycle'] = lifecycle

    @app.before_request
    def authorize():
        # Internal service credential, not frontend session ownership.
        if request.path not in ('/health', '/ready') and api_token:
            if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + api_token).encode()):
                return {'error': 'unauthorized'}, 401

    def body(fields):
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != set(fields):
            raise ValueError('Expected fields: ' + ', '.join(fields))
        return data

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'payment', 'mode': 'mock'}

    @app.get('/ready')
    def ready():
        return {'status': 'ready', 'work': lifecycle.ready()}

    @app.post('/notify/expired')
    def expired():
        return lifecycle.receive_expiry(request.get_json())

    @app.post('/notify/holds')
    def hold_event():
        return lifecycle.receive_event(request.get_json())

    @app.post('/payments')
    def payment():
        row = lifecycle.start_payment(**body(('request_id','hold_id','outcome','attempt_key')))
        return {'payment_id': str(row['payment_id']), 'status': row['status']}

    @app.get('/payments/<payment_id>')
    def status(payment_id):
        return {'status': lifecycle.payment(payment_id)['status']}

    @app.get('/payments/<payment_id>/details')
    def details(payment_id):
        return jsonify(serializable(lifecycle.payment(payment_id)))

    @app.post('/checkouts/cancel')
    def cancel():
        row = lifecycle.start_cancel(**body(('request_id','hold_id','action_key')))
        return jsonify(serializable(row)), 202 if row['status']=='pending' else 200

    @app.get('/cancellations/<action_id>')
    def cancellation(action_id):
        return jsonify(serializable(lifecycle.cancellation(action_id)))

    @app.get('/checkouts/<hold_id>')
    def checkout(hold_id):
        cached = request.args.get('cached', 'false')
        if cached not in ('true', 'false'):
            raise ValueError('cached must be true or false')
        return jsonify(serializable(lifecycle.checkout(request.args.get('request_id'),hold_id,refresh=cached!='true')))

    @app.errorhandler(Conflict)
    def conflict(exc):
        return {'error': 'conflict', 'message': str(exc)}, 409

    @app.errorhandler(NotFound)
    def missing(exc):
        return {'error': 'not_found', 'message': str(exc)}, 404

    @app.errorhandler(ValueError)
    def invalid(exc):
        return {'error': 'invalid_input', 'message': str(exc)}, 400

    @app.errorhandler(DependencyError)
    @app.errorhandler(psycopg.Error)
    @app.errorhandler(requests.RequestException)
    def unavailable(exc):
        app.logger.warning('Payment dependency unavailable: %s', type(exc).__name__)
        return {'error': 'dependency_unavailable', 'message': 'Retry the same operation'}, 503

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return {'error': exc.name.lower().replace(' ', '_'), 'message': exc.description}, exc.code

    @app.errorhandler(Exception)
    def unexpected(exc):
        app.logger.error('Payment internal failure: %s', type(exc).__name__)
        return {'error': 'internal_error'}, 500

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init-db','serve','worker','work-status','retry-work'))
    parser.add_argument('--work-id')
    args = parser.parse_args()
    config = settings()
    lifecycle = Lifecycle(Database(config['database_url']),
        SeatClient(config['seat_url'],config['timeout'],config['cancel_path']),config['status_url'])
    logging.basicConfig(level=logging.INFO)
    if args.command == 'init-db':
        lifecycle.initialize()
    elif args.command == 'serve':
        create_app(lifecycle, config['api_token']).run(host=config['host'],port=config['port'],use_reloader=False)
    elif args.command == 'retry-work':
        if not args.work_id:
            parser.error('retry-work requires --work-id')
        print(lifecycle.retry_work(args.work_id))
    elif args.command == 'work-status':
        print(lifecycle.work_status())
    else:
        lifecycle.ready()
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            try:
                count = lifecycle.recover(limit=10, stop=stop)
                if count:
                    logging.info('Payment recovery processed=%s', count)
            except psycopg.Error:
                logging.error('Payment database unavailable; durable work retained')
            stop.wait(config['interval'])


if __name__ == '__main__':
    main()
