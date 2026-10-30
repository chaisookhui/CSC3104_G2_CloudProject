"""Run alongside the API: python recovery.py. Safe to run on multiple Pods."""
import logging
import os
import signal
import threading
import requests
from queue_store import RedisStore


def run():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    store = RedisStore(os.environ['REDIS_URL'], os.getenv('QUEUE_KEY', 'ticketing:default:queue'))
    url = os.getenv('DISPATCHER_URL', 'http://localhost:5005').rstrip('/')
    while not stop.is_set():
        try:
            phase = store.client.hget(store.keys[0], 'phase')
            if phase == 'OPENING':
                result = store.open_sale()
                phase = 'OPEN' if result['sale_state'] == 'sale_started' else 'OPENING'
            if phase == 'OPEN':
                # Dispatcher persists batch identity before handoff; retries reuse it.
                requests.post(url + '/batches/next', timeout=(3, 5)).raise_for_status()
        except Exception:
            logging.exception('Recovery tick failed; durable state retained')
        stop.wait(1)


if __name__ == '__main__':
    run()
