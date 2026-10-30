"""Repeat against one and multiple Pods; writes JSON measurements to stdout."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
from uuid import uuid4
import requests

p = argparse.ArgumentParser()
p.add_argument('--url', default='http://127.0.0.1:5001')
p.add_argument('--mode', choices=['register', 'poll'], default='register')
p.add_argument('--requests', type=int, default=1000)
p.add_argument('--concurrency', type=int, default=32)
p.add_argument('--request-id', help='Poll a single request instead of aggregate status')
a = p.parse_args()
prefix = str(uuid4())
def run(i):
    start = time.perf_counter()
    try:
        if a.mode == 'register':
            r = requests.post(a.url + '/submit', json={'user_id':prefix+str(i), 'section':'ABCD'[i%4], 'party_size':i%4+1}, timeout=30)
        else:
            r = requests.get(a.url + ('/requests/' + a.request_id if a.request_id else '/status'), timeout=30)
        return time.perf_counter()-start, r.status_code
    except requests.RequestException:
        return time.perf_counter()-start, 0
start = time.perf_counter()
with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
    results = list(pool.map(run, range(a.requests)))
elapsed = time.perf_counter()-start
latencies = sorted(t for t, _ in results)
def percentile(q):
    return round(latencies[max(0, math.ceil(len(latencies)*q)-1)]*1000, 2)
print(json.dumps(dict(mode=a.mode, requests=a.requests, concurrency=a.concurrency,
    elapsed_seconds=round(elapsed,3), throughput_rps=round(a.requests/elapsed,2),
    p50_ms=percentile(.5), p95_ms=percentile(.95), p99_ms=percentile(.99),
    errors=sum(not 200<=code<300 for _,code in results)), indent=2))
