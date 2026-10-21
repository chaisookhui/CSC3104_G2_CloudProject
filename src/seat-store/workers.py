"""Expiry housekeeping and leased, at-least-once webhook delivery."""

import logging
from threading import Event, Thread
from uuid import uuid4

import requests

LOG = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(self, database, waitlist_url, timeout=5, sender=None):
        self.db = database
        self.url = waitlist_url.rstrip("/") + "/notify/expired"
        self.timeout = timeout
        self.sender = sender or requests.post

    def deliver_one(self):
        token = uuid4()
        # Claim briefly, then close the transaction BEFORE the network request.
        with self.db.connect() as conn:
            event = conn.execute("""
                UPDATE notification_outbox SET
                    lease_token = %s,
                    lease_until = clock_timestamp() + %s * INTERVAL '1 second',
                    attempts = attempts + 1
                WHERE event_id = (
                    SELECT event_id FROM notification_outbox
                    WHERE delivered_at IS NULL AND next_attempt_at <= clock_timestamp()
                      AND (lease_until IS NULL OR lease_until <= clock_timestamp())
                    ORDER BY next_attempt_at, created_at
                    FOR UPDATE SKIP LOCKED LIMIT 1
                ) RETURNING *
            """, (token, max(30, self.timeout + 10))).fetchone()
        if event is None:
            return False
        delivered = False
        try:
            response = self.sender(self.url, json=event["payload"], timeout=self.timeout,
                                   allow_redirects=False)
            response.raise_for_status()
            body = response.json()
            delivered = (200 <= response.status_code < 300 and isinstance(body, dict)
                         and body.get("success") is True)
        except (requests.RequestException, ValueError):
            pass
        with self.db.connect() as conn:
            if delivered:
                conn.execute("""
                    UPDATE notification_outbox SET delivered_at = clock_timestamp(),
                        lease_token = NULL, lease_until = NULL
                    WHERE event_id = %s AND lease_token = %s
                """, (event["event_id"], token))
            else:
                delay = min(300, 2 ** min(event["attempts"], 9))
                conn.execute("""
                    UPDATE notification_outbox SET lease_token = NULL, lease_until = NULL,
                        next_attempt_at = clock_timestamp() + %s * INTERVAL '1 second'
                    WHERE event_id = %s AND lease_token = %s
                """, (delay, event["event_id"], token))
                LOG.warning("Expiry callback pending retry: event_id=%s attempt=%s",
                            event["event_id"], event["attempts"])
        return True


class BackgroundTasks:
    def __init__(self, store, config):
        self.store = store
        self.dispatcher = OutboxDispatcher(store.db, config["WAITLIST_URL"],
                                           config["CALLBACK_TIMEOUT_SECONDS"])
        self.stop_event = Event()
        self.threads = [
            Thread(target=self._loop, args=(self.store.expire_due, config["EXPIRY_SCAN_INTERVAL"]),
                   name="hold-expiry", daemon=True),
            Thread(target=self._deliver, args=(config["CALLBACK_INTERVAL"],),
                   name="expiry-callbacks", daemon=True),
        ]

    def _loop(self, operation, interval):
        while not self.stop_event.is_set():
            try:
                operation()
            except Exception:
                # Do not log connection strings or passwords from database exceptions.
                LOG.error("Background operation failed; retrying: %s", operation.__name__)
            self.stop_event.wait(interval)

    def _deliver(self, interval):
        def batch():
            for _ in range(10):
                if self.stop_event.is_set() or not self.dispatcher.deliver_one():
                    break
        self._loop(batch, interval)

    def start(self):
        for thread in self.threads:
            thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=self.dispatcher.timeout + 2)

