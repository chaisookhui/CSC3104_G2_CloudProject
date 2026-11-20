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

    def update(self, operation, append_safe=False, request_ids=None, batch_id=None, claim=False):
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

    def activity(self):
        state = self.read()
        return dict(sale_state=state['sale_state'],
                    queued_count=sum(p['status']=='QUEUED' for p in state['requests'].values()))

    def next_queued(self, limit):
        state = self.read()
        return dict(sale_state=state['sale_state'], requests=[state['requests'][rid]
            for rid in state['queue'] if state['requests'][rid]['status']=='QUEUED'][:limit])

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

    Registration and bounded numbering use Lua. Batch transitions retain Python
    validation and use a fenced patch that commutes with append-only registration.
    General mutations keep the global WATCH transaction. Derived queued/batch
    indexes bound hot-path reads and are repaired atomically after legacy writes.
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
 if redis.call('HEXISTS', KEYS[1], 'queued_count') == 1 then
  redis.call('HINCRBY', KEYS[1], 'queued_count', 1)
 end
 p.queue_number = n; p.status = 'QUEUED'; p.entry_type = 'latecomer'
 local now = redis.call('TIME'); p.eligible_at = tonumber(now[1]) + tonumber(now[2])/1000000
 redis.call('ZADD', KEYS[4], n, ARGV[2])
 redis.call('ZADD', KEYS[8], n, ARGV[2])
end
local encoded = cjson.encode(p)
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('HSET', KEYS[3], ARGV[2], encoded)
redis.call('INCR', KEYS[6])
local registrations = redis.call('INCR', KEYS[7])
if tonumber(redis.call('HGET', KEYS[1], 'indexed_registrations')) == registrations - 1 then
 redis.call('HSET', KEYS[1], 'indexed_registrations', registrations)
end
return {encoded, '201'}
"""

    # Global revision still fences legacy writers. Subtracting the count of
    # append-only registrations lets a batch transition commute with new users,
    # while another transition (or any legacy writer) still invalidates it.
    TRANSITION = """
local revision = tonumber(redis.call('GET', KEYS[6]) or '0')
local registrations = tonumber(redis.call('GET', KEYS[7]) or '0')
if revision - registrations ~= tonumber(ARGV[1]) then return 0 end
local changes = cjson.decode(ARGV[2])
if next(changes) == nil then return 1 end
if tonumber(redis.call('HGET', KEYS[1], 'activity_revision')) ~= tonumber(ARGV[1]) then return 0 end
if redis.call('HEXISTS', KEYS[1], 'queued_count') == 0 then return 0 end
if tonumber(redis.call('HGET', KEYS[1], 'indexes_revision')) ~= tonumber(ARGV[1]) then return 0 end
if tonumber(redis.call('HGET', KEYS[1], 'indexed_registrations')) ~= registrations then return 0 end
local function memberships(p)
 local result = {}
 for _, field in ipairs({'batch_id','last_batch_id'}) do
  if type(p[field]) == 'string' then result[p[field]] = true end
 end
 return result
end
local function batch_change(batch, rid, add)
 local ids = cjson.decode(redis.call('HGET', KEYS[9], batch) or '[]')
 local updated = {}
 for _, old in ipairs(ids) do if old ~= rid then table.insert(updated, old) end end
 if add then table.insert(updated, rid) end
 if #updated == 0 then redis.call('HDEL', KEYS[9], batch)
 else redis.call('HSET', KEYS[9], batch, cjson.encode(updated)) end
end
for rid, encoded in pairs(changes) do
 local old = cjson.decode(redis.call('HGET', KEYS[3], rid))
 local p = cjson.decode(encoded)
 if p.status == 'QUEUED' then redis.call('ZADD', KEYS[8], p.queue_number, rid)
 else redis.call('ZREM', KEYS[8], rid) end
 local previous = memberships(old); local current = memberships(p)
 for batch,_ in pairs(previous) do if not current[batch] then batch_change(batch,rid,false) end end
 for batch,_ in pairs(current) do if not previous[batch] then batch_change(batch,rid,true) end end
 redis.call('HSET', KEYS[3], rid, encoded)
end
redis.call('HINCRBY', KEYS[1], 'queued_count', ARGV[3])
redis.call('HSET', KEYS[1], 'activity_revision', tonumber(ARGV[1]) + 1,
 'indexes_revision', tonumber(ARGV[1]) + 1)
redis.call('INCR', KEYS[6])
return 1
"""
    ACTIVITY = """
local phase = redis.call('HGET', KEYS[1], 'phase') or 'PRE_SALE'
if phase == 'PRE_SALE' then return {phase, '0'} end
local registrations = tonumber(redis.call('GET', KEYS[7]) or '0')
local revision = tonumber(redis.call('GET', KEYS[6]) or '0') - registrations
local count = redis.call('HGET', KEYS[1], 'queued_count')
if not count or tonumber(redis.call('HGET', KEYS[1], 'activity_revision')) ~= revision
 or tonumber(redis.call('HGET', KEYS[1], 'indexes_revision')) ~= revision
 or tonumber(redis.call('HGET', KEYS[1], 'indexed_registrations')) ~= registrations then
 count = 0
 redis.call('DEL', KEYS[8], KEYS[9])
 local records = redis.call('HGETALL', KEYS[3]); local batches = {}
 for i=1,#records,2 do
  local rid = records[i]; local p = cjson.decode(records[i+1])
  if p.status == 'QUEUED' then
   count = count + 1; redis.call('ZADD', KEYS[8], p.queue_number, rid)
  elseif phase == 'OPENING' and p.status == 'REGISTERED' then count = count + 1 end
  for _, field in ipairs({'batch_id','last_batch_id'}) do
   local batch = p[field]
   if type(batch) == 'string' then
    if not batches[batch] then batches[batch] = {} end
    batches[batch][rid] = true
   end
  end
 end
 for batch, members in pairs(batches) do
  local ids = {}; for rid,_ in pairs(members) do table.insert(ids,rid) end
  redis.call('HSET', KEYS[9], batch, cjson.encode(ids))
 end
 redis.call('HSET', KEYS[1], 'queued_count', count, 'activity_revision', revision,
  'indexes_revision', revision, 'indexed_registrations', registrations)
end
return {phase, tostring(count)}
"""
    BATCH_SNAPSHOT = """
local phase = redis.call('HGET', KEYS[1], 'phase') or 'PRE_SALE'
local registrations = tonumber(redis.call('GET', KEYS[7]) or '0')
local revision = tonumber(redis.call('GET', KEYS[6]) or '0') - registrations
if phase ~= 'OPEN'
 or tonumber(redis.call('HGET', KEYS[1], 'indexes_revision')) ~= revision
 or tonumber(redis.call('HGET', KEYS[1], 'indexed_registrations')) ~= registrations then return {'RETRY'} end
local ids = {}; for _,rid in ipairs(cjson.decode(ARGV[1])) do ids[rid] = true end
local queue = {}
if tonumber(ARGV[3]) > 0 then
 queue = redis.call('ZRANGE', KEYS[8], 0, tonumber(ARGV[3])-1)
 for _,rid in ipairs(queue) do ids[rid] = true end
else
 for _,rid in ipairs(cjson.decode(redis.call('HGET', KEYS[9], ARGV[2]) or '[]')) do ids[rid] = true end
end
local records = {}
for rid,_ in pairs(ids) do
 local raw = redis.call('HGET', KEYS[3], rid)
 if raw then records[rid] = raw end
end
return {cjson.encode(redis.call('HGETALL', KEYS[1])),cjson.encode(records),cjson.encode(queue),tostring(revision)}
"""
    OPEN = """
local phase = redis.call('HGET', KEYS[1], 'phase') or 'PRE_SALE'
local started = '1'
if phase == 'PRE_SALE' then
 started = '0'
 local count = redis.call('ZCARD', KEYS[5])
 redis.call('HSET', KEYS[1], 'phase', 'OPENING', 'initial_count', count,
            'cursor', 0, 'next_number', count + 1, 'queued_count', count)
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
  redis.call('ZADD', KEYS[8], cursor, rid)
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
                     ('meta', 'users', 'requests', 'queue', 'lottery', 'revision',
                      'registrations_revision', 'queued', 'batches')]
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

    def activity(self):
        """O(1) normally; atomically heal metadata after a legacy writer."""
        self._check_layout()
        phase, count = self.client.eval(self.ACTIVITY, len(self.keys), *self.keys)
        sale = {'PRE_SALE':'pre_sale', 'OPENING':'opening', 'OPEN':'sale_started'}[phase or 'PRE_SALE']
        return dict(sale_state=sale, queued_count=int(count))

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

    def _read(self, client, with_revision=False):
        # MULTI readers get a coherent view across the component keys.
        with client.pipeline() as p:
            p.hgetall(self.keys[0]); p.hgetall(self.keys[1]); p.hgetall(self.keys[2]); p.zrange(self.keys[3], 0, -1)
            if with_revision:
                p.get(self.keys[5]); p.get(self.keys[6])
            values = p.execute()
            meta, users, records, queue = values[:4]
        state = self._decode_state(meta, users, records, queue)
        return (state, int(values[4] or 0)-int(values[5] or 0)) if with_revision else state

    @staticmethod
    def _decode_state(meta, users, records, queue):
        requests = {rid: json.loads(raw) for rid, raw in records.items()}
        for party in requests.values():
            if meta.get('eligible_at') and party.get('queue_number') and 'eligible_at' not in party:
                party['eligible_at'] = float(meta['eligible_at'])
        return dict(sale_state={'PRE_SALE':'pre_sale', 'OPENING':'opening', 'OPEN':'sale_started'}[meta.get('phase', 'PRE_SALE')],
                    next_number=int(meta.get('next_number', 1)), users=users,
                    requests=requests, queue=queue)

    def _batch_snapshot(self, request_ids, batch_id, limit):
        raw = self.client.eval(self.BATCH_SNAPSHOT, len(self.keys), *self.keys,
                               json.dumps(request_ids), batch_id, limit)
        if raw == ['RETRY']:
            return None
        flat = json.loads(raw[0])
        state = self._decode_state(dict(zip(flat[::2],flat[1::2])), {},
                                   json.loads(raw[1]) or {}, list(json.loads(raw[2])))
        return state, int(raw[3])

    def next_queued(self, limit):
        if not 1 <= limit <= 100:
            raise ValueError('Queue limit must be between 1 and 100')
        for _ in range(100):
            activity = self.activity()
            if activity['sale_state'] != 'sale_started':
                return dict(sale_state=activity['sale_state'],requests=[])
            snapshot = self._batch_snapshot([], '', limit)
            if snapshot is not None:
                state, _ = snapshot
                return dict(sale_state=state['sale_state'],
                            requests=[state['requests'][rid] for rid in state['queue']])
        raise RuntimeError('Queue busy; retry request')

    def read(self):
        self._check_layout()
        return self._read(self.client)

    def update(self, operation, append_safe=False, request_ids=None, batch_id=None, claim=False):
        if append_safe:
            return self._update_transition(operation, request_ids, batch_id, claim)
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
                    if state['sale_state'] == 'sale_started':
                        # WATCH(revision) also fences registration and OPEN Lua
                        # writers. Set the exact count in the same commit as the
                        # state transition; idempotent retries cannot decrement twice.
                        pipe.hset(self.keys[0], 'queued_count',
                                  sum(p['status']=='QUEUED' for p in state['requests'].values()))
                    pipe.incr(self.keys[5])
                    pipe.execute()
                    return deepcopy(result)
                except self.redis_module.WatchError:
                    continue
        raise RuntimeError('Queue busy; retry request')

    def _update_transition(self, operation, request_ids=None, batch_id=None, claim=False):
        """Keep Python claim/outcome validation; atomically patch existing rows.

        Only the explicitly append-safe API callbacks use this path. New parties
        always append after existing global positions, so cannot change a valid
        earliest-batch claim. Structural mutations retain the global WATCH path.
        """
        self._check_layout()
        for _ in range(100):
            activity = self.activity()
            if request_ids is not None and activity['sale_state'] == 'sale_started':
                snapshot = self._batch_snapshot(request_ids, batch_id, len(request_ids) if claim else 0)
                if snapshot is None:
                    continue
                before, revision = snapshot
            else:
                before, revision = self._read(self.client, with_revision=True)
            state = deepcopy(before)
            result = operation(state)
            changes = {rid: party for rid, party in state['requests'].items()
                       if party != before['requests'].get(rid)}
            allowed = {'status', 'batch_id', 'last_batch_id', 'allocation'}
            if (any(state[key] != before[key] for key in ('users','queue','next_number','sale_state'))
                    or state['requests'].keys() != before['requests'].keys()
                    or any({k:v for k,v in party.items() if k not in allowed} !=
                           {k:v for k,v in before['requests'][rid].items() if k not in allowed}
                           for rid,party in changes.items())):
                raise ValueError('Append-safe transition may only change existing batch outcome fields')
            delta = sum(int(p['status']=='QUEUED')-int(before['requests'][rid]['status']=='QUEUED')
                        for rid,p in changes.items())
            committed = self.client.eval(self.TRANSITION, len(self.keys), *self.keys, revision,
                json.dumps({rid:json.dumps(party) for rid,party in changes.items()}), delta)
            if committed:
                return deepcopy(result)
        raise RuntimeError('Queue busy; retry request')
