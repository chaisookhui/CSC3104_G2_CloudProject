"""Payment API and separate durable recovery worker; no seat-store imports."""
import argparse
import hmac
import logging
import signal
import threading
from time import perf_counter

import psycopg
import requests
from psycopg_pool import PoolTimeout, TooManyRequests, PoolClosed
from flask import Flask, jsonify, request, g, Response
from werkzeug.exceptions import HTTPException
from payment_db import Database
from payment_settings import settings
from lifecycle import Conflict, DependencyError, Lifecycle, NotFound, SeatClient
from payment_monitoring import HttpMetrics, snapshot, render_shared
from payment_security import CheckoutTokens, install_customer_routes
from payment_audit import record as audit
from payment_serialization import serializable


def create_app(lifecycle=None, api_token=None, *, rate_limit=600, rate_window=60,
               checkout_key='', customer_outcome='success'):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
    if lifecycle is None:
        config = settings()
        lifecycle = Lifecycle(Database(config['database_url']),
            SeatClient(config['seat_url'], config['timeout'], config['cancel_path']), config['status_url'],
            max_pending=config['max_pending'],max_attempts_per_hold=config['max_attempts_per_hold'])
        if api_token is None:
            api_token = config['api_token']
        rate_limit, rate_window = config['rate_limit'], config['rate_window']
        checkout_key, customer_outcome = config['checkout_key'], config['customer_outcome']
    if rate_limit < 1 or rate_window < 1:
        raise ValueError('Rate limits must be positive')
    api_token = api_token or ''
    if checkout_key and checkout_key==api_token:
        raise ValueError('Checkout signing key must differ from internal service token')
    if customer_outcome not in ('success','decline','timeout'):
        raise ValueError('Invalid server-side customer mock outcome')
    tokens = CheckoutTokens(checkout_key) if checkout_key else None
    metrics = HttpMetrics()
    app.extensions['lifecycle'] = lifecycle
    app.extensions['http_metrics'] = metrics

    @app.before_request
    def authorize():
        g.started_at=perf_counter()
        g.audit_actor='service' if api_token else 'development'
        if request.path.startswith('/customer/'):
            from werkzeug.exceptions import NotFound, Unauthorized
            if not tokens:
                raise NotFound('Customer checkout is not enabled')
            credential=request.headers.get('Authorization','')
            if not credential.startswith('Bearer '):
                raise Unauthorized('Checkout credential required')
            scope='read' if request.method in ('GET','HEAD') else ('cancel' if request.endpoint=='customer_cancel' else 'pay')
            g.checkout_grant=tokens.verify(credential[7:],scope)
        # Internal service credential, not frontend session ownership.
        elif request.path not in ('/health', '/ready') and api_token:
            if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + api_token).encode()):
                return {'error': 'unauthorized'}, 401
        # Authenticate before touching storage; never trust forwarded client IDs.
        if request.endpoint and request.path not in ('/health', '/ready', '/metrics'):
            scope = 'event' if request.path.startswith('/notify/') else ('read' if request.method in ('GET','HEAD') else 'write')
            allowed, retry_after = lifecycle.consume_rate(scope, rate_limit, rate_window)
            if not allowed:
                return {'error': 'rate_limited', 'message': 'Shared service quota reached; retry later'}, 429, {'Retry-After': str(retry_after)}

    @app.after_request
    def security_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.path not in ('/health','/ready','/metrics'):
            metrics.observe(request.endpoint or 'unmatched',response.status_code,
                            perf_counter()-g.get('started_at',perf_counter()))
        return response

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

    @app.get('/metrics')
    def monitoring():
        return Response('\n'.join(metrics.render()+render_shared(snapshot(lifecycle.db)))+'\n',
                        content_type='text/plain; version=0.0.4; charset=utf-8')

    @app.post('/notify/expired')
    def expired():
        return lifecycle.receive_expiry(request.get_json())

    @app.post('/notify/holds')
    def hold_event():
        return lifecycle.receive_event(request.get_json())

    @app.post('/payments')
    def payment():
        row = lifecycle.start_payment(**body(('request_id','hold_id','outcome','attempt_key')),actor=g.audit_actor)
        return {'payment_id': str(row['payment_id']), 'status': row['status']}

    @app.get('/payments/<payment_id>')
    def status(payment_id):
        return {'status': lifecycle.payment(payment_id)['status']}

    @app.get('/payments/<payment_id>/details')
    def details(payment_id):
        return jsonify(serializable(lifecycle.payment(payment_id)))

    @app.post('/checkouts/cancel')
    def cancel():
        row = lifecycle.start_cancel(**body(('request_id','hold_id','action_key')),actor=g.audit_actor)
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
    @app.errorhandler(PoolTimeout)
    @app.errorhandler(TooManyRequests)
    @app.errorhandler(PoolClosed)
    def unavailable(exc):
        app.logger.warning('Payment dependency unavailable: %s', type(exc).__name__)
        return {'error': 'dependency_unavailable', 'message': 'Retry the same operation'}, 503, {'Retry-After': '3'}

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return {'error': exc.name.lower().replace(' ', '_'), 'message': exc.description}, exc.code

    @app.errorhandler(Exception)
    def unexpected(exc):
        app.logger.error('Payment internal failure: %s', type(exc).__name__)
        return {'error': 'internal_error'}, 500

    if tokens:
        install_customer_routes(app,lifecycle,customer_outcome)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init-db','serve','worker','work-status','retry-work','monitor','issue-checkout-token'))
    parser.add_argument('--work-id')
    parser.add_argument('--subject')
    parser.add_argument('--request-id')
    parser.add_argument('--hold-id')
    parser.add_argument('--ttl',type=int,default=900)
    parser.add_argument('--scopes',default='read,pay,cancel')
    args = parser.parse_args()
    config = settings()
    lifecycle = Lifecycle(Database(config['database_url']),
        SeatClient(config['seat_url'],config['timeout'],config['cancel_path']),config['status_url'],
        max_pending=config.get('max_pending',5000),max_attempts_per_hold=config.get('max_attempts_per_hold',10))
    logging.basicConfig(level=logging.INFO)
    if args.command == 'init-db':
        lifecycle.initialize()
    elif args.command == 'serve':
        from waitress import serve
        serve(create_app(lifecycle, config['api_token'], rate_limit=config['rate_limit'], rate_window=config['rate_window'],
                         checkout_key=config.get('checkout_key',''),customer_outcome=config.get('customer_outcome','success')),
              host=config['host'], port=config['port'], threads=config['threads'],
              connection_limit=config['connection_limit'], backlog=100,
              channel_timeout=30, max_request_body_size=16*1024,
              max_request_header_size=16*1024, expose_tracebacks=False)
    elif args.command == 'retry-work':
        if not args.work_id:
            parser.error('retry-work requires --work-id')
        print(lifecycle.retry_work(args.work_id))
    elif args.command == 'work-status':
        print(lifecycle.work_status())
    elif args.command == 'monitor':
        import json
        print(json.dumps(snapshot(lifecycle.db),default=str,indent=2))
    elif args.command == 'issue-checkout-token':
        if not all((args.subject,args.request_id,args.hold_id,config['checkout_key'])):
            parser.error('Token issuance requires signing key, --subject, --request-id and --hold-id')
        issuer=CheckoutTokens(config['checkout_key'])
        lifecycle.checkout(args.request_id,args.hold_id)  # verify the real hold binding
        token=issuer.issue(args.subject,args.request_id,args.hold_id,ttl=args.ttl,scopes=args.scopes.split(','))
        with lifecycle.db.connect() as conn:
            audit(conn,'checkout.token_issued',actor='operator',request_id=args.request_id,
                  hold_id=args.hold_id,subject=args.subject,scopes=args.scopes.split(','))
        print(token)
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
