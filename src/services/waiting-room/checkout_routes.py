"""Exact-hold checkout discovery and cancellation.

These remain trusted prototype APIs: a supplied user_id is not authentication.
"""
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, Conflict, NotFound, ServiceUnavailable
import requests


def validate_allocation(value):
    try:
        if not isinstance(value, dict) or set(value) != {'hold_id', 'hold_status', 'hold_expiry', 'seats'}:
            raise ValueError()
        UUID(value['hold_id'])
        seats = value['seats']
        if (value['hold_status'] not in ('ACTIVE', 'CONFIRMED') or not isinstance(seats, list)
                or not 1 <= len(seats) <= 4 or any(not isinstance(s, str) or not s for s in seats)
                or len(set(seats)) != len(seats)):
            raise ValueError()
        if value['hold_status'] == 'ACTIVE':
            deadline = datetime.fromisoformat(value['hold_expiry'].replace('Z', '+00:00'))
            if deadline.tzinfo is None:
                raise ValueError()
        elif value['hold_expiry'] is not None:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid checkout allocation') from None


def install_checkout_routes(app, store, sections, http):
    payment_url = os.getenv('PAYMENT_URL', 'http://127.0.0.1:5004').rstrip('/')
    allocator_url = os.getenv('ALLOCATOR_URL', 'http://127.0.0.1:5002').rstrip('/')

    def call(method, url, *, payment=False, **kwargs):
        headers = {}
        if payment and os.getenv('PAYMENT_API_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['PAYMENT_API_TOKEN']
        try:
            response = http.request(method, url, timeout=(3, 5), allow_redirects=False,
                                    headers=headers, **kwargs)
            if response.status_code == 409:
                raise Conflict('Checkout operation conflicts with current booking state')
            response.raise_for_status()
            if not 200 <= response.status_code < 300:
                raise ValueError()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data, response.status_code
        except (requests.RequestException, ValueError):
            raise ServiceUnavailable('Checkout dependency unavailable; retry the same request') from None

    def party_for(rid):
        party = store.get_request(rid)
        if party is None:
            raise NotFound('Request not found')
        return party

    def allocation_for(party):
        allocation = party.get('allocation')
        batch_id = party.get('batch_id') or party.get('last_batch_id')
        # Expose a finished party immediately, even while the rest of its batch runs.
        if allocation is None and batch_id and party['status'] in ('ADMITTED', 'RESERVED'):
            batch, _ = call('GET', allocator_url + '/batches/' + batch_id)
            if batch.get('batch_id') != batch_id or not isinstance(batch.get('jobs'), list):
                raise ServiceUnavailable('Invalid allocation response')
            jobs = [j for j in batch['jobs'] if isinstance(j, dict) and j.get('request_id') == party['request_id']]
            if len(jobs) == 1 and jobs[0].get('state') == 'RESERVED':
                result = jobs[0].get('result') or {}
                allocation = {k: result.get(k) for k in ('hold_id', 'hold_status', 'hold_expiry', 'seats')}
        if allocation is None:
            raise Conflict('No allocated checkout is available yet')
        try:
            allocation = validate_allocation(allocation)
        except ValueError:
            raise ServiceUnavailable('Invalid allocation checkout details') from None
        if len(allocation['seats']) != party['party_size']:
            raise ServiceUnavailable('Checkout party size mismatch')
        return allocation

    def refreshed_checkout(party):
        allocation = allocation_for(party)
        result, _ = call('GET', payment_url + '/checkouts/' + allocation['hold_id'], payment=True,
                         params={'request_id': party['request_id']})
        if (result.get('request_id') != party['request_id'] or result.get('hold_id') != allocation['hold_id']
                or result.get('booking_status') not in ('active', 'confirmed', 'expired', 'cancelled')
                or result.get('cached') is True or result.get('source') != 'seat-store'):
            raise ServiceUnavailable('Invalid or stale checkout response')
        return result

    @app.get('/requests/<rid>/checkout')
    def checkout(rid):
        return jsonify(refreshed_checkout(party_for(rid)))

    @app.post('/requests/<rid>/cancel')
    def cancel(rid):
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'action_key'}
                or not isinstance(data['action_key'], str) or not 1 <= len(data['action_key'].strip()) <= 128):
            raise BadRequest('Supply action_key; reuse it on retry')
        party = party_for(rid)
        allocation = allocation_for(party)
        result, code = call('POST', payment_url + '/checkouts/cancel', payment=True, json={
            'request_id': rid, 'hold_id': allocation['hold_id'], 'action_key': data['action_key']})
        return jsonify(result), code

    @app.post('/requests/<rid>/rejoin')
    def rejoin(rid):
        # The original request is the idempotency key for this new attempt.
        party = party_for(rid)
        if party.get('rejoined_to'):
            return jsonify(party_for(party['rejoined_to'])), 200
        if party['status'] != 'UNAVAILABLE':
            checkout = refreshed_checkout(party)
            if checkout['booking_status'] not in ('expired', 'cancelled'):
                raise Conflict('Only rejected, expired or cancelled attempts may rejoin')
        new_id = str(uuid4())
        def commit(state):
            original = state['requests'][rid]
            if original.get('rejoined_to'):
                return state['requests'][original['rejoined_to']], 200
            if state['sale_state'] != 'sale_started':
                raise Conflict('Initial numbering is not ready')
            if state['users'].get(original['user_id']) != rid:
                raise Conflict('Another attempt is already active')
            number = state['next_number']
            state['next_number'] += 1
            new = dict(request_id=new_id, user_id=original['user_id'],
                       section=original['section'], party_size=original['party_size'],
                       timestamp=datetime.now(timezone.utc).isoformat(),
                       entry_type='latecomer', queue_number=number, status='QUEUED',
                       previous_request_id=rid)
            original['rejoined_to'] = new_id
            state['requests'][new_id] = new
            state['users'][original['user_id']] = new_id
            state['queue'].append(new_id)
            return new, 201
        result, code = store.update(commit)
        return jsonify(result), code
