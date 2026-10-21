import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest
from uuid import uuid4

from store import SeatStore
from workers import BackgroundTasks, OutboxDispatcher


@pytest.fixture
def receiver():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.received.append((self.path, payload))
            self.server.observer(payload)
            status, body = self.server.replies.pop(0) if self.server.replies else (200, {"success": True})
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.received, server.replies = [], []
    server.observer = lambda payload: None
    server.url = f"http://127.0.0.1:{server.server_port}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def enqueue(store, make_due):
    hold = store.hold("A", 2, "callback")
    make_due(hold["hold_id"])
    store.expire_due()
    return hold


def test_real_webhook_runs_after_commit_and_outside_seat_locks(db, store, make_due, receiver):
    enqueue(store, make_due)
    # Module 4 may synchronously reserve another party while handling the callback.
    receiver.observer = lambda payload: store.hold("A", 2, "reallocated")
    dispatcher = OutboxDispatcher(db, receiver.url, timeout=3)
    assert dispatcher.deliver_one()
    assert not dispatcher.deliver_one()
    assert receiver.received[0][0] == "/notify/expired"
    assert receiver.received[0][1]["request_id"] == "callback"
    with db.connect() as conn:
        assert conn.execute("SELECT delivered_at FROM notification_outbox").fetchone()["delivered_at"]


@pytest.mark.parametrize("first_reply", [(503, {"success": False}), (200, {"success": False})])
def test_failed_callbacks_survive_dispatcher_restart(db, store, make_due, receiver, first_reply):
    enqueue(store, make_due)
    receiver.replies = [first_reply, (200, {"success": True})]
    assert OutboxDispatcher(db, receiver.url).deliver_one()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM notification_outbox").fetchone()
        assert row["delivered_at"] is None and row["attempts"] == 1
        assert row["lease_token"] is None
        conn.execute("UPDATE notification_outbox SET next_attempt_at = clock_timestamp()")
    assert OutboxDispatcher(db, receiver.url).deliver_one()
    assert len(receiver.received) == 2
    assert receiver.received[0][1]["event_id"] == receiver.received[1][1]["event_id"]
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM notification_outbox").fetchone()
        assert row["delivered_at"] is not None and row["attempts"] == 2


def test_abandoned_delivery_lease_is_recovered(db, store, make_due, receiver):
    enqueue(store, make_due)
    with db.connect() as conn:
        conn.execute("UPDATE notification_outbox SET lease_until = clock_timestamp() - INTERVAL '1 second', "
                     "lease_token = %s, attempts = 1", (uuid4(),))
    assert OutboxDispatcher(db, receiver.url).deliver_one()
    with db.connect() as conn:
        assert conn.execute("SELECT attempts FROM notification_outbox").fetchone()["attempts"] == 2


def test_running_background_threads_expire_and_notify(db, store, make_due, receiver):
    hold = store.hold("A", 2, "background")
    make_due(hold["hold_id"])
    delivered = Event()
    receiver.observer = lambda payload: delivered.set()
    config = {"WAITLIST_URL": receiver.url, "CALLBACK_TIMEOUT_SECONDS": 2,
              "EXPIRY_SCAN_INTERVAL": 0.05, "CALLBACK_INTERVAL": 0.05}
    tasks = BackgroundTasks(SeatStore(db), config).start()
    try:
        assert delivered.wait(timeout=10), "Background expiry did not reach the webhook"
    finally:
        tasks.stop()
    assert not any(thread.is_alive() for thread in tasks.threads)
    assert all(s["state"] == "AVAILABLE" for s in store.list_seats("A"))

