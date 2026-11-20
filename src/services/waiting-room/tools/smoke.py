"""Verify a live, isolated test deployment. prepare, restart services, then verify."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from uuid import uuid4
import requests

p = argparse.ArgumentParser()
p.add_argument('phase', choices=['prepare', 'verify'])
p.add_argument('--url', default='http://127.0.0.1:5001')
p.add_argument('--snapshot', default='/tmp/waiting-room-smoke.json')
a = p.parse_args()
def call(method, path, **kwargs):
    r = requests.request(method, a.url + path, timeout=20, **kwargs)
    r.raise_for_status()
    return r.json()
if a.phase == 'prepare':
    prefix = str(uuid4())
    def submit(user):
        return call('POST', '/submit', json={'user_id':user, 'section':'A', 'party_size':1})
    with ThreadPoolExecutor(max_workers=24) as pool:
        duplicates = list(pool.map(submit, [prefix]*48))
    assert len({r['request_id'] for r in duplicates}) == 1
    call('POST', '/sale/start')
    for _ in range(100):
        if call('GET', '/status')['sale_state'] == 'sale_started':
            break
        time.sleep(.1)
    else:
        raise AssertionError('Opening did not recover')
    with ThreadPoolExecutor(max_workers=24) as pool:
        late = list(pool.map(submit, [prefix+str(i) for i in range(100)]))
    numbers = sorted(r['queue_number'] for r in late)
    assert len(set(numbers)) == 100
    assert numbers == list(range(numbers[0], numbers[0]+100))
    before = call('GET', '/queue')
    call('POST', '/sale/start')
    assert call('GET', '/queue') == before
    Path(a.snapshot).write_text(json.dumps(before))
    print('PASS: duplicate burst, opening, late numbering, repeated start; snapshot saved')
else:
    assert call('GET', '/ready')['status'] == 'ready'
    assert call('GET', '/queue') == json.loads(Path(a.snapshot).read_text())
    print('PASS: queue and request records survived restart')
