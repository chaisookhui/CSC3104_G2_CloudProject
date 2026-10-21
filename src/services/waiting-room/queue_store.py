"""Single-process development storage and shared Redis prototype storage."""
from copy import deepcopy
import json
from threading import Lock


def empty_state():
    return {"sale_state": "pre_sale", "requests": {}, "users": {},
            "queue": [], "next_number": 1}


class MemoryStore:
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


class RedisStore:
    """WATCH/MULTI makes the cutoff, numbering atomic across Pods.

    This prototype stores a JSON snapshot; use normalized Redis keys/SQL records
    for large events to avoid copying the full event on every submission.
    """
    def __init__(self, url, key):
        import redis
        self.redis_module = redis
        self.client = redis.Redis.from_url(url, decode_responses=True,
                                           socket_connect_timeout=3, socket_timeout=3)
        self.key = key

    def update(self, operation):
        for _ in range(100):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(self.key)
                    raw = pipe.get(self.key)
                    state = json.loads(raw) if raw else empty_state()
                    result = operation(state)
                    pipe.multi()
                    pipe.set(self.key, json.dumps(state))
                    pipe.execute()
                    return deepcopy(result)
                except self.redis_module.WatchError:
                    continue
        raise RuntimeError("Queue busy; retry request")

    def read(self):
        raw = self.client.get(self.key)
        return json.loads(raw) if raw else empty_state()
