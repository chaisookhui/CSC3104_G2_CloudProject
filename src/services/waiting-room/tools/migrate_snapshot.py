"""Offline migration: stop old API/dispatcher writers before running this once.

Retains the original snapshot as <QUEUE_KEY>:legacy. Never overwrites v2 data.
"""
import json
import os
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from queue_store import RedisStore

store = RedisStore(os.environ['REDIS_URL'], os.getenv('QUEUE_KEY', 'ticketing:default:queue'))
legacy = store.key.removesuffix(':v2')
with store.client.pipeline() as p:
    p.watch(legacy, legacy + ':legacy', *store.keys)
    raw = p.get(legacy)
    if raw is None or p.exists(legacy + ':legacy', *store.keys):
        raise SystemExit('Source missing or destination exists; no changes made')
    state = json.loads(raw)
    phase = {'pre_sale':'PRE_SALE', 'sale_started':'OPEN'}[state['sale_state']]
    p.multi()
    p.hset(store.keys[0], mapping={'phase':phase, 'next_number':state['next_number'],
                                 'initial_count':sum(r['entry_type']=='waiting_room' for r in state['requests'].values())})
    if state['users']:
        p.hset(store.keys[1], mapping=state['users'])
    if state['requests']:
        p.hset(store.keys[2], mapping={rid:json.dumps(r) for rid,r in state['requests'].items()})
    if state['queue']:
        p.zadd(store.keys[3], {rid:state['requests'][rid]['queue_number'] for rid in state['queue']})
    if phase == 'PRE_SALE' and state['requests']:
        p.zadd(store.keys[4], {rid:random.SystemRandom().random() for rid in state['requests']})
    p.incr(store.keys[5])
    p.rename(legacy, legacy + ':legacy')
    p.execute()
print('Migrated snapshot; original retained as ' + legacy + ':legacy')
