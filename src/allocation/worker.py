"""One general-purpose worker process; run the same command in every replica."""
import logging
import os
import signal
import threading

if __package__:
    from .dispatcher_client import notify_one
    from .job_store import JobStore
    from .seat_client import hold_seats, SeatStoreError
else:
    from dispatcher_client import notify_one
    from job_store import JobStore
    from seat_client import hold_seats, SeatStoreError

log = logging.getLogger(__name__)


def process_one(store, hold=hold_seats, lease_seconds=30, max_attempts=5):
    claim = store.claim(lease_seconds=lease_seconds, max_attempts=max_attempts)
    if claim is None:
        return False
    job = claim["job"]
    try:
        response = hold(job["section"], job["party_size"], job["request_id"])
        result = ({**response, "state": "RESERVED"} if response["success"] else
                  {"state": "UNAVAILABLE", "success": False, "seats": [], "hold_expiry": None})
        accepted = store.finish(claim, result=result)
        log.info("request=%s section=%s outcome=%s ack=%s", job["request_id"], job["section"], result["state"], accepted)
    except SeatStoreError as exc:
        store.finish(claim, error=str(exc), retryable=exc.retryable, max_attempts=max_attempts)
        log.warning("request=%s error=%s", job["request_id"], exc)
    # Unexpected errors leave the claim unacknowledged for lease recovery.
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    store = JobStore(os.environ["ALLOCATION_DATABASE_URL"])
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            worked = process_one(store)
            notify_one(store, os.getenv("DISPATCHER_COMPLETION_URL"))
            if not worked:
                stop.wait(0.5)
        except Exception:
            log.exception("Worker paused after queue/processing failure; pending jobs remain durable")
            stop.wait(2)


if __name__ == "__main__":
    main()
