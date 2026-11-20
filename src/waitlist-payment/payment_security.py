"""Reservation-scoped bearer capabilities issued only by a trusted operator/gateway.

This is not customer login. No public token-minting endpoint exists. Internal
service credentials are deliberately independent from checkout signing material.
"""
import hashlib
import time
from uuid import UUID

from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.exceptions import Unauthorized, Forbidden
from payment_serialization import serializable


class CheckoutTokens:
    audience = 'payment-checkout-v1'
    scopes = frozenset(('read','pay','cancel'))

    def __init__(self, key):
        if len(key) < 32:
            raise ValueError('Checkout signing key must contain at least 32 characters')
        self.serializer = URLSafeTimedSerializer(key, salt=self.audience,
                                                signer_kwargs={'digest_method':hashlib.sha256})

    def issue(self, subject, request_id, hold_id, *, ttl=900, scopes=('read','pay','cancel')):
        if (not isinstance(subject,str) or not subject.strip() or len(subject)>128
                or not isinstance(request_id,str) or not request_id.strip() or len(request_id)>128
                or type(ttl) is not int or not 1 <= ttl <= 900
                or not scopes or not set(scopes) <= self.scopes):
            raise ValueError('Invalid checkout token grant')
        now = int(time.time())
        return self.serializer.dumps({'aud':self.audience,'sub':subject,'request_id':request_id,
            'hold_id':str(UUID(str(hold_id))),'scopes':sorted(set(scopes)),'iat':now,'exp':now+ttl})

    def verify(self, token, scope):
        try:
            data = self.serializer.loads(token,max_age=900)
            now = int(time.time())
            if (not isinstance(data,dict) or data.get('aud')!=self.audience
                    or type(data.get('iat')) is not int or type(data.get('exp')) is not int
                    or not data['iat'] <= now < data['exp'] <= data['iat']+900
                    or any(not isinstance(data.get(k),str) or not data[k].strip() or len(data[k])>128
                           for k in ('sub','request_id','hold_id'))
                    or str(UUID(data['hold_id']))!=data['hold_id']
                    or not isinstance(data.get('scopes'),list) or not data['scopes']
                    or any(not isinstance(s,str) or s not in self.scopes for s in data['scopes'])):
                raise ValueError()
        except (BadData,ValueError,TypeError,KeyError):
            raise Unauthorized('Invalid or expired checkout credential') from None
        if scope not in data['scopes']:
            raise Forbidden('Checkout credential does not permit this action')
        return data


def install_customer_routes(app, lifecycle, mock_outcome):
    """Additive customer facade. IDs come from the signed grant, never user JSON."""
    from flask import g, jsonify, request
    from werkzeug.exceptions import BadRequest, NotFound

    def fields(expected):
        data=request.get_json()
        if not isinstance(data,dict) or set(data)!=set(expected):
            raise BadRequest('Expected fields: '+', '.join(expected))
        return data

    @app.get('/customer/checkout')
    def customer_checkout():
        grant=g.checkout_grant
        return jsonify(serializable(lifecycle.checkout(grant['request_id'],grant['hold_id'])))

    @app.post('/customer/payments')
    def customer_pay():
        grant=g.checkout_grant
        data=fields(('attempt_key',))
        row=lifecycle.start_payment(grant['request_id'],grant['hold_id'],mock_outcome,data['attempt_key'],actor=grant['sub'])
        return {'payment_id':str(row['payment_id']),'status':row['status']}

    @app.get('/customer/payments/<payment_id>')
    def customer_payment(payment_id):
        grant=g.checkout_grant
        row=lifecycle.payment(payment_id)
        if row['request_id']!=grant['request_id'] or str(row['hold_id'])!=grant['hold_id']:
            raise NotFound('Payment not found')
        return {'payment_id':str(row['payment_id']),'status':row['status'],'attempt_status':row['attempt_status']}

    @app.post('/customer/cancel')
    def customer_cancel():
        grant=g.checkout_grant
        data=fields(('action_key',))
        row=lifecycle.start_cancel(grant['request_id'],grant['hold_id'],data['action_key'],actor=grant['sub'])
        return {'action_id':str(row['action_id']),'status':row['status']},202 if row['status']=='pending' else 200

    @app.get('/customer/cancellations/<action_id>')
    def customer_cancellation(action_id):
        grant=g.checkout_grant
        row=lifecycle.cancellation(action_id)
        if row['request_id']!=grant['request_id'] or str(row['hold_id'])!=grant['hold_id']:
            raise NotFound('Cancellation not found')
        return {'action_id':str(row['action_id']),'status':row['status']}
