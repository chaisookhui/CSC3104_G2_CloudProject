"""Exact-hold checkout discovery and explicit, idempotent rejoining.

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
        party = store.read()['requests'].get(rid)
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
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) - {'user_id', 'section', 'party_size'}:
            raise BadRequest('Supply user_id and optional section/party_size')
        old = party_for(rid)
        if data.get('user_id') != old['user_id']:
            raise NotFound('Request does not belong to supplied user')
        section, size = data.get('section', old['section']), data.get('party_size', old['party_size'])
        if not isinstance(section, str) or section not in sections or type(size) is not int or not 1 <= size <= 4:
            raise BadRequest('Invalid section or party size')

        def existing(state):
            current = state['requests'][rid]
            successor = current.get('rejoin_request_id')
            if successor:
                party = state['requests'][successor]
                if party['section'] != section or party['party_size'] != size:
                    raise Conflict('Rejoin was already accepted with different preferences')
                return party
            return None

        previous = existing(store.read())
        if previous:
            return jsonify(previous), 200
        if old['status'] == 'RESERVED':
            checkout = refreshed_checkout(old)
            if checkout['booking_status'] not in ('expired', 'cancelled'):
                raise Conflict('Only expired or cancelled checkouts can rejoin')
        elif old['status'] != 'UNAVAILABLE':
            raise Conflict('Request is still active or has no terminal allocation outcome')
        new_id = str(uuid4())

        def append(state):
            previous = existing(state)
            if previous:
                return previous, 200
            current = state['requests'][rid]
            if (state['sale_state'] != 'sale_started' or current['status'] != old['status']
                    or state['users'].get(old['user_id']) != rid
                    or current.get('allocation') != old.get('allocation')):
                raise Conflict('Registration changed; refresh before rejoining')
            party = {'request_id': new_id, 'user_id': old['user_id'], 'section': section,
                     'party_size': size, 'timestamp': datetime.now(timezone.utc).isoformat(),
                     'entry_type': 'latecomer', 'queue_number': state['next_number'],
                     'status': 'QUEUED', 'previous_request_id': rid}
            state['next_number'] += 1
            state['requests'][new_id] = party
            state['users'][old['user_id']] = new_id
            state['queue'].append(new_id)
            current['rejoin_request_id'] = new_id
            return party, 201

        result, code = store.update(append)
        return jsonify(result), code
