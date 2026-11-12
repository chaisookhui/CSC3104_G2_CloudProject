"""Shared Redis records; atomic commits define FCFS, never client timestamps."""
from copy import deepcopy
import json
import os
import random
import time
from threading import Lock


def empty_state():
    return {"sale_state": "pre_sale", "requests": {}, "users": {},
            "queue": [], "next_number": 1}


class MemoryStore:
    """Explicit test/development store. Never use with multiple workers."""
    def __init__(self):
        self.state = empty_state()
        self.lock = Lock()

    def update(self, operation):
        with self.lock:
            state = deepcopy(self.state)
            result = operation(state)
            self.state = state
            return deepcopy(result)

    def read(self):
        with self.lock:
            return deepcopy(self.state)

    def get_request(self, rid):
        return self.read()['requests'].get(rid)

    def ready(self):
        return True

    def register(self, party):
        def operation(state):
            user, rid = party['user_id'], party['request_id']
            if user in state['users']:
                return state['requests'][state['users'][user]], 200
            if state['sale_state'] != 'pre_sale':
                party.update(entry_type='latecomer', queue_number=state['next_number'], status='QUEUED', eligible_at=time.time())
                state['next_number'] += 1
                state['queue'].append(rid)
            state['users'][user] = rid
            state['requests'][rid] = party
            return party, 201
        return self.update(operation)

    def open_sale(self, batch_size=200):
        def operation(state):
            started = state['sale_state'] != 'pre_sale'
            if not started:
                ids = list(state['requests'])
                random.SystemRandom().shuffle(ids)
                eligible_at = time.time()
                for n, rid in enumerate(ids, 1):
                    state['requests'][rid].update(queue_number=n, status='QUEUED', eligible_at=eligible_at)
                state.update(queue=ids, next_number=len(ids)+1, sale_state='sale_started')
            return dict(sale_state=state['sale_state'], already_started=started,
                        initial_count=sum(p['entry_type']=='waiting_room' for p in state['requests'].values()),
                        next_queue_number=state['next_number'])
        return self.update(operation)


class RedisStore:
    """Versioned namespace; existing snapshot keys are deliberately never overwritten.

    Registration and bounded numbering use Lua. Legacy batch transition functions
    use optimistic transactions, writing only changed hash fields and zset entries.
    Their full read is a remaining optimization opportunity for very large batches.
    """
    REGISTER = """
local old = redis.call('HGET', KEYS[2], ARGV[1])
if old then return {redis.call('HGET', KEYS[3], old), '200'} end
local p = cjson.decode(ARGV[3])
local phase = redis.call('HGET', KEYS[1], 'phase') or 'PRE_SALE'
if phase == 'PRE_SALE' then
 redis.call('ZADD', KEYS[5], ARGV[4], ARGV[2])
else
 local n = redis.call('HINCRBY', KEYS[1], 'next_number', 1) - 1
 p.queue_number = n; p.status = 'QUEUED'; p.entry_type = 'latecomer'
 local now = redis.call('TIME'); p.eligible_at = tonumber(now[1]) + tonumber(now[2])/1000000
 redis.call('ZADD', KEYS[4], n, ARGV[2])
end
local encoded = cjson.encode(p)
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('HSET', KEYS[3], ARGV[2], encoded)
redis.call('INCR', KEYS[6])
return {encoded, '201'}
"""
    OPEN = """
local phase = redis.call('HGET', KEYS[1], 'phase') or 'PRE_SALE'
local started = '1'
if phase == 'PRE_SALE' then
 started = '0'
 local count = redis.call('ZCARD', KEYS[5])
 redis.call('HSET', KEYS[1], 'phase', 'OPENING', 'initial_count', count,
            'cursor', 0, 'next_number', count + 1)
end
if redis.call('HGET', KEYS[1], 'phase') == 'OPENING' then
 local cursor = tonumber(redis.call('HGET', KEYS[1], 'cursor'))
 local ids = redis.call('ZRANGE', KEYS[5], cursor, cursor + tonumber(ARGV[1]) - 1)
 for _, rid in ipairs(ids) do
  cursor = cursor + 1
  local p = cjson.decode(redis.call('HGET', KEYS[3], rid))
  p.queue_number = cursor; p.status = 'QUEUED'
  redis.call('HSET', KEYS[3], rid, cjson.encode(p))
  redis.call('ZADD', KEYS[4], cursor, rid)
 end
 redis.call('HSET', KEYS[1], 'cursor', cursor)
 if cursor == tonumber(redis.call('HGET', KEYS[1], 'initial_count')) then
  redis.call('HSET', KEYS[1], 'phase', 'OPEN')
  local now = redis.call('TIME')
  redis.call('HSET', KEYS[1], 'eligible_at', tonumber(now[1]) + tonumber(now[2])/1000000)
 end
 redis.call('INCR', KEYS[6])
end
return {redis.call('HGET', KEYS[1], 'phase'), started,
 redis.call('HGET', KEYS[1], 'initial_count'), redis.call('HGET', KEYS[1], 'next_number')}
"""

    def __init__(self, url, key):
        import redis
        self.redis_module = redis
        self.client = redis.Redis.from_url(url, decode_responses=True,
                                           socket_connect_timeout=3, socket_timeout=10)
        self._layout_checked = False
        self.key = key + ':v2'
        self.keys = [self.key + ':' + suffix for suffix in
                     ('meta', 'users', 'requests', 'queue', 'lottery', 'revision')]
        self._register = self.client.register_script(self.REGISTER)
        self._open = self.client.register_script(self.OPEN)

    def _check_layout(self):
        if not self._layout_checked:
            if self.client.exists(self.key.removesuffix(':v2')):
                raise RuntimeError('Legacy snapshot found; stop old writers and run tools/migrate_snapshot.py')
            self._layout_checked = True

    def ready(self):
        self._check_layout()
        return self.client.ping()

    def register(self, party):
        self._check_layout()
        raw, code = self._register(keys=self.keys, args=[party['user_id'], party['request_id'],
                                                       json.dumps(party), random.SystemRandom().random()])
        return json.loads(raw), int(code)

    def open_sale(self, batch_size=200):
        self._check_layout()
        phase, started, count, number = self._open(keys=self.keys, args=[batch_size])
        return dict(sale_state={'PRE_SALE':'pre_sale', 'OPENING':'opening', 'OPEN':'sale_started'}[phase],
                    already_started=started=='1', initial_count=int(count), next_queue_number=int(number))

    def prepare_replay(self, ordered_users):
        """Lab fixture only: set lottery scores before opening a registered queue.

        No HTTP endpoint exposes this operation. The experiment CLI invokes it
        inside the lab Pod. Normal/demo registration still uses SystemRandom.
        """
        if os.getenv('EXPERIMENT_NAMESPACE') not in ('csc3104-lab', 'csc3104-check'):
            raise RuntimeError('Replay fixtures are allowed only in the lab or disposable verification namespace')
        if (not isinstance(ordered_users, list) or not ordered_users or
                any(not isinstance(user, str) or not user for user in ordered_users) or
                len(set(ordered_users)) != len(ordered_users)):
            raise ValueError('Replay users must be a nonempty unique list')
        self._check_layout()
        script = """
if (redis.call('HGET', KEYS[1], 'phase') or 'PRE_SALE') ~= 'PRE_SALE' then
 return redis.error_reply('Replay requires PRE_SALE')
end
if redis.call('HLEN', KEYS[2]) ~= #ARGV then
 return redis.error_reply('Replay must include every registered user')
end
local ids = {}
for i,user in ipairs(ARGV) do
 local rid = redis.call('HGET', KEYS[2], user)
 if not rid then return redis.error_reply('Unknown replay user') end
 ids[i] = rid
end
for i,rid in ipairs(ids) do redis.call('ZADD', KEYS[5], i, rid) end
return #ids
"""
        return self.client.eval(script, len(self.keys), *self.keys, *ordered_users)

    def get_request(self, rid):
        self._check_layout()
        raw = self.client.hget(self.keys[2], rid)
        if not raw:
            return None
        party = json.loads(raw)
        eligible = self.client.hget(self.keys[0], 'eligible_at')
        if eligible and party.get('queue_number') and 'eligible_at' not in party:
            party['eligible_at'] = float(eligible)
        return party

    def _read(self, client):
        # MULTI readers get a coherent view across the component keys.
        with client.pipeline() as p:
            p.hgetall(self.keys[0]); p.hgetall(self.keys[1]); p.hgetall(self.keys[2]); p.zrange(self.keys[3], 0, -1)
            meta, users, records, queue = p.execute()
        requests = {rid: json.loads(raw) for rid, raw in records.items()}
        for party in requests.values():
            if meta.get('eligible_at') and party.get('queue_number') and 'eligible_at' not in party:
                party['eligible_at'] = float(meta['eligible_at'])
        return dict(sale_state={'PRE_SALE':'pre_sale', 'OPENING':'opening', 'OPEN':'sale_started'}[meta.get('phase', 'PRE_SALE')],
                    next_number=int(meta.get('next_number', 1)), users=users,
                    requests=requests, queue=queue)

    def read(self):
        self._check_layout()
        return self._read(self.client)

    def update(self, operation):
        for _ in range(100):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(self.keys[5])
                    before = self.read()
                    state = deepcopy(before)
                    result = operation(state)
                    pipe.multi()
                    for rid, party in state['requests'].items():
                        if before['requests'].get(rid) != party:
                            pipe.hset(self.keys[2], rid, json.dumps(party))
                    for user, rid in state['users'].items():
                        if before['users'].get(user) != rid:
                            pipe.hset(self.keys[1], user, rid)
                    old_queue = set(before['queue'])
                    for rid in state['queue']:
                        if rid not in old_queue:
                            pipe.zadd(self.keys[3], {rid: state['requests'][rid]['queue_number']})
                    for rid in old_queue - set(state['queue']):
                        pipe.zrem(self.keys[3], rid)
                    if state['next_number'] != before['next_number']:
                        pipe.hset(self.keys[0], 'next_number', state['next_number'])
                    pipe.incr(self.keys[5])
                    pipe.execute()
                    return deepcopy(result)
                except self.redis_module.WatchError:
                    continue
        raise RuntimeError('Queue busy; retry request')
