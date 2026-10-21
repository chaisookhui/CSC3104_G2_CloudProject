"""Trusted local mock-payment API; run recovery as a separate worker process."""

import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg
import requests
from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'seat-store'))
from db import Database
from settings import settings
from lifecycle import Conflict, Lifecycle, SeatClient


def create_app(lifecycle=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
    if lifecycle is None:
        lifecycle = Lifecycle(Database(settings()['DATABASE_URL']),
                              SeatClient(os.getenv('SEAT_STORE_URL', 'http://127.0.0.1:5003')))
    app.extensions['lifecycle'] = lifecycle

    @app.post('/notify/expired')
    def expired():
        return lifecycle.receive_expiry(request.get_json())

    @app.post('/payments')
    def payment():
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != {'request_id', 'hold_id', 'outcome', 'attempt_key'}:
            raise ValueError('Expected request_id, hold_id, outcome, attempt_key')
        row = lifecycle.start_payment(**data)
        return jsonify({'payment_id': str(row['payment_id']), 'status': row['status']})

    @app.get('/payments/<payment_id>')
    def status(payment_id):
        payment_id = UUID(payment_id)
        with lifecycle.db.connect() as conn:
            row = conn.execute('SELECT status FROM wy_payments WHERE payment_id=%s', (payment_id,)).fetchone()
        return (jsonify(row), 200) if row else ({'error': 'not_found'}, 404)

    @app.errorhandler(Conflict)
    def conflict(exc):
        return {'error': 'conflict', 'message': str(exc)}, 409

    @app.errorhandler(ValueError)
    @app.errorhandler(KeyError)
    @app.errorhandler(TypeError)
    def invalid(exc):
        return {'error': 'invalid_input'}, 400

    @app.errorhandler(psycopg.Error)
    @app.errorhandler(requests.RequestException)
    def unavailable(exc):
        return {'error': 'dependency_unavailable', 'message': 'Retry the same operation'}, 503

    return app


if __name__ == '__main__':
    import argparse
    import logging
    import time

    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init-db', 'serve', 'worker'])
    args = parser.parse_args()
    app = create_app()
    lifecycle = app.extensions['lifecycle']
    if args.command == 'init-db':
        lifecycle.initialize()
    elif args.command == 'serve':
        app.run(host='127.0.0.1', port=5004, use_reloader=False)
    else:
        while True:
            try:
                lifecycle.recover()
            except (psycopg.Error, requests.RequestException):
                logging.error('Recovery dependency unavailable; durable work retained')
            time.sleep(1)
