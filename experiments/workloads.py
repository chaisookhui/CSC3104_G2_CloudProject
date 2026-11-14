"""Saved, deterministic workloads and real-network lab measurements."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import csv
import hashlib
import json
import math
import random
import threading
import time

from runtime import api, guard_lab, invariants, k, request, utc, write_json
from fairness import fairness_summary


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def same_deadline(first, second):
    try:
        left=datetime.fromisoformat(first.replace('Z','+00:00'))
        right=datetime.fromisoformat(second.replace('Z','+00:00'))
        return left.tzinfo is not None and right.tzinfo is not None and left==right
    except (AttributeError,TypeError,ValueError):
        return False


def make_trace(scenario='F1', count=40, seed=42, batch_size=10):
    if scenario not in [f'F{i}' for i in range(1, 8)] or not 1 <= count <= 500 or not 1 <= batch_size <= 100:
        raise ValueError('Use F1-F7, 1-500 customers and batch size 1-100')
    rng = random.Random(seed)
    combinations = [(section, size) for section in 'ABCD' for size in range(1, 5)]
    rng.shuffle(combinations)
    parties = []
    for index in range(count):
        section, size = combinations[index % len(combinations)]
        if scenario == 'F2':
            section, size = rng.choice('ABCD'), rng.choices([1, 2, 3, 4], weights=[70, 10, 10, 10])[0]
        elif scenario == 'F3':
            section, size = rng.choice('ABCD'), rng.choices([1, 2, 3, 4], weights=[10, 10, 10, 70])[0]
        elif scenario == 'F4':
            section = 'A' if rng.random() < .8 else rng.choice('BCD')
            size = rng.randint(1, 4)
        wave = int(scenario == 'F7' and index >= max(1, count // 2))
        action = ['confirm', 'cancel', 'expire'][index % 3] if scenario == 'F7' and wave == 0 else 'confirm'
        parties.append(dict(trace_id=f'customer-{index+1}', user_id=f'trace-{scenario}-{seed}-{index+1}',
                            section=section, party_size=size, queue_number=index+1, wave=wave,
                            action=action, action_delay_seconds=1))
    return dict(version=1, scenario=scenario, seed=seed, batch_size=batch_size,
                fixture='scarce-80' if scenario == 'F5' else 'alternating' if scenario == 'F6' else 'empty',
                customers=parties)


def validate_trace(trace):
    if trace.get('version') != 1 or trace.get('fixture') not in ('empty', 'scarce-80', 'alternating'):
        raise ValueError('Unsupported trace version or inventory fixture')
    parties = trace.get('customers', [])
    if not 1 <= len(parties) <= 500 or not 1 <= trace.get('batch_size', 0) <= 100:
        raise ValueError('Trace needs 1-500 customers and batch size 1-100')
    for field in ('trace_id', 'user_id', 'queue_number'):
        if len({party.get(field) for party in parties}) != len(parties):
            raise ValueError('Trace contains duplicate ' + field)
    if sorted(p['queue_number'] for p in parties) != list(range(1, len(parties)+1)):
        raise ValueError('Queue numbers must be exactly 1..N')
    for p in parties:
        if (p.get('section') not in tuple('ABCD') or type(p.get('party_size')) is not int or
                p['party_size'] not in range(1, 5) or type(p.get('wave')) is not int or p.get('wave') not in (0, 1) or
                p.get('action') not in ('confirm', 'cancel', 'expire') or
                not isinstance(p.get('user_id'), str) or not 1 <= len(p['user_id']) <= 128 or
                not isinstance(p.get('action_delay_seconds'), (int, float)) or not 0 <= p['action_delay_seconds'] <= 60):
            raise ValueError('Invalid customer in trace')
    ordered = sorted(parties, key=lambda p: p['queue_number'])
    if ordered[0]['wave'] != 0 or [p['wave'] for p in ordered] != sorted(p['wave'] for p in ordered):
        raise ValueError('Wave zero must precede optional wave one')
    return trace


def percentile(values, percent):
    values = sorted(values)
    if not values:
        return None
    at = (len(values)-1) * percent / 100
    lower = math.floor(at)
    return values[lower] + (values[math.ceil(at)] - values[lower]) * (at-lower)


def write_rows(directory, rows, filename='customers'):
    write_json(directory / (filename + '.json'), rows)
    fields = sorted(set().union(*(row.keys() for row in rows))) if rows else ['outcome']
    with (directory / (filename + '.csv')).open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def registration(base, payload):
    attempts = []
    for _ in range(3):
        response = request(base, 'waiting-room/submit', payload)
        attempts.append(response)
        if response['status'] in (200, 201) and isinstance(response['data'], dict) and response['data'].get('request_id'):
            return dict(outcome='ACCEPTED', request=response['data'], attempts=attempts)
        if 400 <= response['status'] < 500:
            return dict(outcome='REJECTED', attempts=attempts)
        time.sleep(.2)
    # Unknown replies are reconciled with the same identity, not a new UUID.
    response = request(base, 'waiting-room/queue')
    if response['status'] == 200:
        match = next((p for p in response['data']['requests'] if p['user_id'] == payload['user_id']), None)
        if match:
            return dict(outcome='ACCEPTED_RECONCILED', request=match, attempts=attempts)
    return dict(outcome='UNKNOWN', attempts=attempts)


def seat_snapshot(base):
    return [seat for section in 'ABCD' for seat in api(base, 'seats/seats/' + section)]


def seat_fingerprint(seats):
    return digest(sorted((s['seat_id'], s['section'], s['row'], s['position_in_row'], s['state']) for s in seats))


def inventory_fixture(base, fixture):
    seats = seat_snapshot(base)
    if any(s['state'] != 'AVAILABLE' for s in seats):
        raise RuntimeError('Replay requires a fresh, fully available development inventory')
    if fixture == 'empty':
        return seats
    if fixture == 'scarce-80':
        for section in 'ABCD':
            for index in range(math.floor(sum(s['section'] == section for s in seats) * .8)):
                rid = f'fixture-{section}-{index}'
                held = api(base, 'seats/seats/hold', dict(request_id=rid, section=section, party_size=1))
                if not held.get('success'):
                    raise RuntimeError('Could not prepare scarce inventory')
                api(base, 'seats/seats/confirm', dict(request_id=rid, hold_id=held['hold_id']))
    elif fixture == 'alternating':
        # Fill before releasing gaps: immediate release would let first-fit reuse
        # the same early seat. All mutations use seat-store-owned transactions.
        held_seats = []
        for section in 'ABCD':
            for index in range(sum(s['section'] == section for s in seats)):
                rid = f'fixture-{section}-{index}'
                held = api(base, 'seats/seats/hold', dict(request_id=rid, section=section, party_size=1))
                if not held.get('success'):
                    raise RuntimeError('Could not prepare fragmented inventory')
                held_seats.append((rid, held))
        for rid, held in held_seats:
            action = 'confirm' if held['seats'][0]['position_in_row'] % 2 else 'cancel'
            api(base, 'seats/seats/' + action, dict(request_id=rid, hold_id=held['hold_id']))
    return seat_snapshot(base)


def prepare_lottery(ordered_users):
    source = """import os,json,sys
from queue_store import RedisStore
store=RedisStore(os.environ['REDIS_URL'],os.environ['QUEUE_KEY'])
print(store.prepare_replay(json.load(sys.stdin)))
"""
    result = k('exec', '-i', 'deployment/waiting-room', '--', 'python', '-c', source,
               source=json.dumps(ordered_users), capture=True)
    if int(result) != len(ordered_users):
        raise RuntimeError('Replay queue fixture did not include every customer')


def free_blocks(seats):
    rows = defaultdict(list)
    for seat in seats:
        rows[seat['section'], seat['row']].append(seat)
    blocks = {}
    for (section, row), values in rows.items():
        lengths, run = [], 0
        previous = None
        for seat in sorted(values, key=lambda s: s['position_in_row']):
            contiguous = previous is None or seat['position_in_row'] == previous+1
            if seat['state'] == 'AVAILABLE':
                if not contiguous and run:
                    lengths.append(run); run = 0
                run += 1
            elif run:
                lengths.append(run); run = 0
            previous = seat['position_in_row']
        if run:
            lengths.append(run)
        blocks[f'{section}/{row}'] = lengths
    return blocks


def summarize(rows, initial, final, elapsed):
    groups = []
    for section in 'ABCD':
        for size in range(1, 5):
            group = [row for row in rows if row['section'] == section and row['party_size'] == size]
            if not group:
                continue
            waits = [row['decision_wait_seconds'] for row in group if row.get('decision_wait_seconds') is not None]
            groups.append(dict(section=section, party_size=size, offered=len(group),
                reserved=sum(row.get('allocation_state') == 'RESERVED' for row in group),
                confirmed=sum(row.get('outcome') == 'CONFIRMED' for row in group),
                unavailable=sum(row.get('outcome') == 'UNAVAILABLE' for row in group),
                unknown=sum(row.get('outcome') in ('UNKNOWN', 'REGISTERED', 'QUEUED', 'ADMITTED', 'RESERVED') for row in group),
                outcomes=dict(Counter(row['outcome'] for row in group)),
                reservation_rate=sum(row.get('allocation_state') == 'RESERVED' for row in group)/len(group),
                confirmation_rate=sum(row.get('outcome') == 'CONFIRMED' for row in group)/len(group),
                measured_waits=len(waits), median_wait_seconds=percentile(waits, 50),
                p95_wait_seconds=percentile(waits, 95)))
    # Decisions for both winners/losers; compare only same section and fixed batch.
    overtakes = 0
    for earlier in rows:
        for later in rows:
            if (earlier.get('batch_id') and earlier.get('batch_id') == later.get('batch_id') and
                    earlier['section'] == later['section'] and earlier['queue_number'] < later['queue_number'] and
                    earlier.get('decided_at') is not None and later.get('decided_at') is not None and
                    later['decided_at'] < earlier['decided_at']):
                overtakes += 1
    outcomes = dict(Counter(row['outcome'] for row in rows))
    decided = sum(row.get('allocation_state') in ('RESERVED', 'UNAVAILABLE', 'EXPIRED', 'CANCELLED') for row in rows)
    requested_seats=sum(row['party_size'] for row in rows)
    reserved_seats=sum(row['party_size'] for row in rows if row.get('allocation_state')=='RESERVED')
    confirmed_seats=sum(row['party_size'] for row in rows if row.get('outcome')=='CONFIRMED')
    return dict(customers=len(rows), outcomes=outcomes, elapsed_seconds=elapsed,
        allocation_decisions_per_second=decided/elapsed if elapsed else None,
        reservations=sum(row.get('allocation_state') == 'RESERVED' for row in rows),
        confirmations=outcomes.get('CONFIRMED', 0), groups=groups, fairness=fairness_summary(groups), overtakes=overtakes,
        requested_seats=requested_seats,reserved_trace_seats=reserved_seats,confirmed_trace_seats=confirmed_seats,
        seat_reservation_rate=reserved_seats/requested_seats if requested_seats else None,
        seat_confirmation_rate=confirmed_seats/requested_seats if requested_seats else None,
        incremental_venue_utilization=confirmed_seats/len(final) if final else None,
        initial_fingerprint=seat_fingerprint(initial), initial_occupied=sum(s['state'] != 'AVAILABLE' for s in initial),
        final_confirmed=sum(s['state'] == 'CONFIRMED' for s in final),
        final_held=sum(s['state'] == 'HELD' for s in final), total_inventory=len(final), free_blocks=free_blocks(final),
        timing_definition='Allocator database decided_at minus Redis eligible_at, including UNAVAILABLE decisions; clocks must agree.',
        throughput_definition='Client-observed full replay wall time including registration, actions and draining; not isolated allocator service capacity.')


def replay(base, trace, directory, timeout=420):
    context=guard_lab(base); validate_trace(trace)
    status = api(base, 'waiting-room/status')
    if status['sale_state'] != 'pre_sale' or status['waiting_count'] != 0:
        raise RuntimeError('Use a fresh empty pre-sale lab for replay')
    config = json.loads(k('get', 'configmap', 'core-config', '-o', 'json', capture=True))['data']
    if int(config['BATCH_SIZE']) != trace['batch_size']:
        raise RuntimeError('Lab batch size differs from the saved trace')
    if trace['fixture'] == 'alternating' and int(config['HOLD_TTL_SECONDS']) < 120:
        raise RuntimeError('Use --hold-ttl 120 or longer to prepare the fragmented fixture safely')
    policy = api(base, 'allocation/ready').get('policy')
    if policy not in ('demand-cycle', 'fcfs'):
        raise RuntimeError('Rebuild/load the allocator image with policy support first')
    if policy != config.get('ALLOCATION_POLICY'):
        raise RuntimeError('Allocator policy does not match lab configuration; wait for the intended rollout')
    write_json(directory / 'trace.json', trace)
    initial = inventory_fixture(base, trace['fixture'])
    write_json(directory / 'inventory-before.json', initial)
    rows = [{**party, 'outcome': 'UNKNOWN'} for party in sorted(trace['customers'], key=lambda p: p['queue_number'])]
    started = time.monotonic()
    deadline = started + timeout
    final_states = {'CONFIRMED', 'CANCELLED', 'EXPIRED', 'UNAVAILABLE', 'REJECTED'}
    original_dispatcher = None
    try:
        for wave in sorted({row['wave'] for row in rows}):
            active = [row for row in rows if row['wave'] == wave]
            if wave:
                original_dispatcher = json.loads(k('get', 'deployment', 'dispatcher-worker', '-o', 'json', capture=True))['spec']['replicas']
                k('scale', 'deployment/dispatcher-worker', '--replicas=0')
                k('wait', '--for=delete', 'pod', '-l', 'app=dispatcher-worker', '--timeout=90s')
            # Preserve latecomer numbering too: late wave is submitted in saved
            # order while dispatch is paused. Initial pre-sale registrations may overlap.
            def submit(row):
                result = registration(base, {key: row[key] for key in ('user_id', 'section', 'party_size')})
                row['registration'] = result
                row['outcome'] = result['outcome']
                if result.get('request'):
                    row['request_id'] = result['request']['request_id']
                return row
            if wave:
                for row in active: submit(row)
            else:
                with ThreadPoolExecutor(max_workers=min(24, len(active))) as pool:
                    list(pool.map(submit, active))
                if any(not row.get('request_id') for row in active):
                    raise RuntimeError('Replay registration has rejected/unknown customers; preserve and investigate')
                prepare_lottery([row['user_id'] for row in active])
                while api(base, 'waiting-room/sale/start', {})['sale_state'] != 'sale_started':
                    if time.monotonic() >= deadline: raise RuntimeError('Sale opening timed out')
            if wave:
                k('scale', 'deployment/dispatcher-worker', f'--replicas={original_dispatcher}')
                k('rollout', 'status', 'deployment/dispatcher-worker', '--timeout=180s')
                original_dispatcher = None
            def progress(row):
                if row['outcome'] in final_states or not row.get('request_id'):
                    return
                response = request(base, 'waiting-room/requests/' + row['request_id'])
                if response['status'] != 200:
                    row['last_error'] = response; return
                party = response['data']
                if party.get('queue_number') != row['queue_number']:
                    raise RuntimeError('Actual queue order differs from the saved trace')
                row.update(eligible_at=party.get('eligible_at'), batch_id=party.get('batch_id') or party.get('last_batch_id'))
                row['outcome'] = party['status']
                allocation = party.get('allocation')
                if not allocation:
                    return
                row.setdefault('reserved_observed_at', time.monotonic())
                if row.get('hold_id') and row['hold_id'] != allocation['hold_id']:
                    raise RuntimeError('A replay customer changed hold identity')
                if row.get('original_expiry') and not same_deadline(row['original_expiry'],allocation['hold_expiry']):
                    raise RuntimeError('A replay customer changed the original hold deadline')
                row.setdefault('hold_id', allocation['hold_id'])
                row.setdefault('original_expiry', allocation['hold_expiry'])
                row['seats'] = allocation['seats']
                checkout = request(base, 'waiting-room/requests/' + row['request_id'] + '/checkout')
                if checkout['status'] != 200:
                    row['last_error'] = checkout; return
                current = checkout['data']
                if current.get('source') != 'seat-store' or current.get('cached') is True:
                    return
                if current.get('hold_id') != row['hold_id']:
                    raise RuntimeError('Checkout returned a different hold')
                if not same_deadline(current.get('original_hold_expiry'),row['original_expiry']):
                    raise RuntimeError('Authoritative checkout changed the original deadline')
                row['checkout'] = current
                if current['booking_status'] != 'active':
                    row['outcome'] = current['booking_status'].upper(); return
                if time.monotonic()-row['reserved_observed_at'] < row['action_delay_seconds']:
                    return
                if row['action'] == 'confirm' and current.get('can_pay'):
                    row['action_response'] = request(base, 'payment/payments', dict(
                        request_id=row['request_id'], hold_id=row['hold_id'], outcome='success',
                        attempt_key='replay:' + row['user_id']))
                elif row['action'] == 'cancel' and current.get('can_cancel'):
                    row['action_response'] = request(base, 'waiting-room/requests/' + row['request_id'] + '/cancel',
                                                   dict(action_key='replay-cancel:' + row['user_id']))
            while time.monotonic() < deadline:
                with ThreadPoolExecutor(max_workers=min(24, len(active))) as pool:
                    list(pool.map(progress, active))
                write_rows(directory, rows)
                if all(row['outcome'] in final_states for row in active):
                    break
                time.sleep(.5)
            if any(row['outcome'] not in final_states for row in active):
                break
        # Load all recorded fixed-batch jobs, including unsuccessful decisions.
        batches = {}
        for row in rows:
            if row.get('batch_id') and row['batch_id'] not in batches:
                batches[row['batch_id']] = api(base, 'allocation/batches/' + row['batch_id'])
        expected_groups, observed_groups = defaultdict(list), defaultdict(list)
        for wave in sorted({r['wave'] for r in rows}):
            for index, row in enumerate(r for r in rows if r['wave'] == wave):
                expected_groups[wave, index // trace['batch_size']].append(row['queue_number'])
        for batch_id, batch in batches.items():
            if batch.get('policy') != policy:
                raise RuntimeError('A recorded batch used a different allocation policy')
            observed_groups[batch_id] = sorted(j['global_position'] for j in batch['jobs'])
            jobs = {job['request_id']: job for job in batch['jobs']}
            for row in rows:
                job = jobs.get(row.get('request_id'))
                if not job: continue
                row['allocation_state'] = job['state']
                row['priority'] = job['priority']
                row['decided_at'] = (job.get('result') or {}).get('decided_at')
                wait = row['decided_at'] - row['eligible_at'] if row.get('decided_at') is not None and row.get('eligible_at') is not None else None
                row['decision_wait_seconds'] = wait if wait is not None and wait >= 0 else None
        boundaries_match = sorted(expected_groups.values()) == sorted(observed_groups.values())
        final = seat_snapshot(base)
        result = summarize(rows, initial, final, time.monotonic()-started)
        result.update(namespace=context['namespace'], policy=policy, trace_sha256=digest(trace), captured_at=utc(), batch_boundaries_match=boundaries_match,
                      actual_batches=batches, config=config, invariants=invariants())
        result['status'] = 'PASS' if (boundaries_match and result['invariants']['status'] == 'PASS' and
            all(row['outcome'] in final_states for row in rows) and
            all(row.get('decision_wait_seconds') is not None for row in rows)) else 'INCONCLUSIVE'
        if result['invariants']['violations']:
            result['status'] = 'FAIL'
        write_json(directory / 'summary.json', result)
        write_json(directory / 'inventory-after.json', final)
        return result
    finally:
        if original_dispatcher is not None:
            k('scale', 'deployment/dispatcher-worker', f'--replicas={original_dispatcher}')
        for row in rows:
            row.pop('reserved_observed_at', None)
        write_rows(directory, rows)


def arrival_schedule(rate,duration,profile):
    phases=[(0,duration,rate,'baseline')] if profile=='constant' else [
        (0,duration*.25,min(5,rate),'baseline'),
        (duration*.25,duration*.75,rate,'surge'),
        (duration*.75,duration,min(5,rate),'baseline')]
    return [(start+i/rps,phase) for start,end,rps,phase in phases
            for i in range(math.ceil((end-start)*rps)) if start+i/rps<end]


def registration_load(base, directory, rate=5, duration=10, profile='constant', admit=False, timeout=600, fresh=True):
    context=guard_lab(base)
    if not 1 <= rate <= 200 or not 1 <= duration <= 300 or rate*duration > 20000:
        raise ValueError('Use 1-200/s, 1-300 seconds and at most 20,000 offered arrivals')
    status = api(base, 'waiting-room/status')
    if fresh and (status['sale_state'] != 'pre_sale' or status['waiting_count'] != 0):
        raise RuntimeError('Registration load needs an empty pre-sale lab')
    from loadgen import generate
    rows = []
    schedule = arrival_schedule(rate,duration,profile)
    try:
        generator = generate(base, schedule, directory.name, rows)
    finally:
        # Keep every partial row even on interruption or a diagnostic failure.
        write_rows(directory, rows, 'arrivals')
    elapsed = generator['elapsed']
    write_json(directory/'generator.json',generator)
    queue = api(base, 'waiting-room/queue')['requests']
    by_user = {party['user_id']: party for party in queue}
    missing, reconciled = [], 0
    for row in rows:
        stored = by_user.get(row['payload']['user_id'])
        row['stored_request_id'] = stored.get('request_id') if stored else None
        if row['outcome'] == 'ACCEPTED' and (not stored or stored['request_id'] != row['response']['data']['request_id']):
            missing.append(row['payload']['user_id'])
        if row['outcome'] in ('UNKNOWN', 'TIMED_OUT') and stored:
            row['outcome'] = 'ACCEPTED_RECONCILED'; reconciled += 1
    latencies = [row['response']['elapsed_ms'] for row in rows if 'response' in row]
    # Retain arrivals even if sale opening or draining is interrupted later.
    write_rows(directory,rows,'arrivals')
    write_json(directory/'registered-queue.json',queue)
    outcomes = Counter(row['outcome'] for row in rows)
    admission = None
    if admit:
        admission_started=time.perf_counter()
        deadline=time.monotonic()+timeout
        while api(base,'waiting-room/sale/start',{}).get('sale_state') != 'sale_started':
            if time.monotonic()>=deadline: raise RuntimeError('Opening timed out')
            time.sleep(.5)
        numbered=api(base,'waiting-room/queue')['requests']
        write_json(directory/'numbered-queue.json',numbered)
        current=numbered
        original={p['request_id']:p.get('queue_number') for p in numbered}
        while time.monotonic()<deadline:
            current=api(base,'waiting-room/queue')['requests']
            if all(p['status'] not in ('REGISTERED','QUEUED','ADMITTED') for p in current): break
            time.sleep(1)
        current_by_id={p['request_id']:p for p in current}
        changed=[rid for rid,position in original.items() if
                 rid not in current_by_id or current_by_id[rid].get('queue_number')!=position]
        positions=list(original.values())
        correct=all(type(p) is int for p in positions) and sorted(positions)==list(range(1,len(positions)+1))
        terminal={'RESERVED','UNAVAILABLE','CONFIRMED','CANCELLED','EXPIRED'}
        unresolved=[p['request_id'] for p in current if p['status'] not in terminal]
        acknowledged={r['stored_request_id'] for r in rows if r['outcome'].startswith('ACCEPTED')}
        changed.extend(sorted(acknowledged-set(original)))
        admission_elapsed=time.perf_counter()-admission_started
        admission=dict(elapsed_seconds=admission_elapsed,deadline_seconds=timeout,
                       within_deadline=admission_elapsed<=timeout,
                       stable_positions=not changed, contiguous_unique_positions=correct,
                       changed_or_missing_ids=changed, unresolved_ids=unresolved,
                       outcomes=dict(Counter(p['status'] for p in current)), invariants=invariants())
        write_json(directory/'admission.json',admission)
    passed=len(rows)==len(schedule) and all(row['outcome'].startswith('ACCEPTED') for row in rows)
    launch_lags=[max(0,r['launched_seconds']-r['scheduled_seconds']) for r in rows if 'launched_seconds' in r]
    faithful=bool(launch_lags) and len(launch_lags)==len(rows) and max(launch_lags)<=1
    if not faithful:passed=False
    checks=invariants()
    stored_ids=[r['stored_request_id'] for r in rows if r.get('stored_request_id')]
    duplicate_ids=len(stored_ids)-len(set(stored_ids))
    failed=bool(missing) or bool(duplicate_ids) or bool(checks['violations']) or (admission and (admission['changed_or_missing_ids'] or
        not admission['contiguous_unique_positions'] or admission['invariants']['violations']))
    if admission and (admission['unresolved_ids'] or not admission['within_deadline']): passed=False
    result = dict(namespace=context['namespace'],status='FAIL' if failed else 'PASS' if passed else 'INCONCLUSIVE',
                  workload='registrations followed by admission; no client checkout' if admit else 'registration-only; no seat contention or payment', profile=profile, rate=rate, duration=duration,
                  elapsed_including_drain=elapsed, offered=len(rows), outcomes=dict(outcomes), admission=admission,
                  generator=generator,timing_fidelity=faithful,
                  scheduled=len(schedule),launched=sum('launched_seconds' in r for r in rows),
                  accepted=sum(r['outcome'].startswith('ACCEPTED') for r in rows),
                  rejected=sum(r['outcome']=='REJECTED' for r in rows),
                  timed_out=sum(r.get('response',{}).get('timed_out',False) or r.get('response',{}).get('error')=='TimeoutError' for r in rows),
                  http_success=sum(200<=r.get('response',{}).get('status',0)<300 for r in rows),
                  http_failed=sum(not 200<=r.get('response',{}).get('status',0)<300 for r in rows if 'response' in r),
                  upstream_retries=sum(max(0,(r.get('response',{}).get('upstream_attempts') or 1)-1) for r in rows),
                  upstream_attempts_known=sum(r.get('response',{}).get('upstream_attempts') is not None for r in rows),
                  generator_dropped=outcomes.get('DROPPED_GENERATOR',0),
                  average_response_ms=sum(latencies)/len(latencies) if latencies else None,
                  served_by_instance=dict(Counter(r['response']['instance'] for r in rows if r.get('response',{}).get('instance'))),
                  duplicate_registration_ids=duplicate_ids,invariants=checks,
                  max_launch_lag_seconds=max(launch_lags) if launch_lags else None,
                  p95_launch_lag_seconds=percentile(launch_lags,95),
                  phases={phase:dict(offered=sum(r['phase']==phase for r in rows),
                      p95_ms=percentile([r['response']['elapsed_ms'] for r in rows if r['phase']==phase and 'response' in r],95),
                      outcomes=dict(Counter(r['outcome'] for r in rows if r['phase']==phase))) for phase in ('baseline','surge')},
                  achieved_registration_rps=sum(row['outcome'].startswith('ACCEPTED') for row in rows)/elapsed if elapsed else None,
                  p50_ms=percentile(latencies,50), p95_ms=percentile(latencies,95), p99_ms=percentile(latencies,99),
                  missing_acknowledged_ids=missing, reconciled_unknowns=reconciled,
                  generator_warning='Open-loop async client on host, outside Kind. Launch timestamps are transport header sends; latency includes gateway and port-forward. Pool capacity 4096; drops and lag invalidate delivery.')
    write_rows(directory, rows, 'arrivals'); write_json(directory/'summary.json', result)
    return result


def contention(base, directory, count=10, workers=10, mixed=False):
    context=guard_lab(base)
    if not 1 <= count <= 500 or not 1 <= workers <= 64:
        raise ValueError('Use 1-500 requests and 1-64 client workers')
    initial = api(base, 'seats/seats/C')
    if len(initial) != 10 or any(seat['state'] != 'AVAILABLE' for seat in initial):
        raise RuntimeError('Contention test requires the fresh ten-seat Section C fixture')
    lock = threading.Lock(); gate = threading.Event()
    active, peak = 0, 0
    started = time.monotonic()
    def hold(index):
        nonlocal active, peak
        gate.wait()
        with lock:
            active += 1; peak = max(peak, active)
        row = dict(index=index, request_id=f'{directory.name}-{index}', party_size=1+index%4 if mixed else 1,
                   sent_at=utc(), started_seconds=time.monotonic()-started)
        try:
            for _ in range(3):
                response = request(base, 'seats/seats/hold', dict(request_id=row['request_id'], section='C', party_size=row['party_size']))
                if response['status'] and response['status'] < 500: break
            row['response'] = response
            row['outcome'] = ('RESERVED' if response['data'].get('success') else 'UNAVAILABLE') if response['status'] == 200 and isinstance(response['data'], dict) else 'UNKNOWN'
            return row
        finally:
            row['finished_seconds'] = time.monotonic()-started
            with lock: active -= 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(hold, index) for index in range(count)]
        gate.set()
        rows = [future.result() for future in futures]
    checks = invariants()
    final = api(base, 'seats/seats/C')
    outcomes = dict(Counter(row['outcome'] for row in rows))
    invalid=[]; owners={}
    for row in rows:
        if row['outcome']!='RESERVED': continue
        seats=row['response']['data'].get('seats',[])
        positions=sorted(s['position_in_row'] for s in seats)
        if (len(seats)!=row['party_size'] or len({s['row'] for s in seats})!=1 or
                positions!=list(range(positions[0],positions[0]+len(seats)))):
            invalid.append(row['request_id'])
        for seat in seats:
            if seat['seat_id'] in owners: invalid.append(row['request_id'])
            owners[seat['seat_id']]=row['request_id']
    result = dict(namespace=context['namespace'],workload='direct seat-store HTTP contention; bypasses waiting-room/allocator/payment',
                  status='FAIL' if checks['violations'] or invalid or len(owners)>10 else
                  'INCONCLUSIVE' if outcomes.get('UNKNOWN',0) or (count>1 and peak<2) else 'PASS',
                  count=count, workers=workers, mixed_sizes=mixed, invalid_parties=invalid,
                  reserved_seats=len(owners), peak_overlapping_client_requests=peak, outcomes=outcomes,
                  elapsed_seconds=time.monotonic()-started, invariants=checks,
                  overlap_scope='HTTP lifetimes overlap; this does not assert the same number of simultaneous database transactions')
    write_rows(directory, rows); write_json(directory/'summary.json', result)
    write_json(directory/'inventory-before.json',initial); write_json(directory/'inventory-after.json',final)
    return result
