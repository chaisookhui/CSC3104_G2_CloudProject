"""One general-purpose worker process; run the same command in every replica."""
import logging
import os
import signal
import threading
import time

if __package__:
    from .dispatcher_client import notify_one
    from .job_store import JobStore
    from .seat_client import hold_seats, SeatStoreError
else:
    from dispatcher_client import notify_one
    from job_store import JobStore
    from seat_client import hold_seats, SeatStoreError

log = logging.getLogger(__name__)


def process_one(store, hold=hold_seats, lease_seconds=30, max_attempts=0):
    claim = store.claim(lease_seconds=lease_seconds, max_attempts=max_attempts)
    if claim is None:
        return False
    job = claim["job"]
    try:
        response = hold(job["section"], job["party_size"], job["request_id"])
        result = ({**response, "state": response.get('hold_status') if response.get('hold_status') in ('EXPIRED','CANCELLED') else 'RESERVED'} if response["success"] else
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
    listener = None
    listener_retry_at = 0
    try:
        while not stop.is_set():
            try:
                if not store.sqlite and listener is None and time.monotonic() >= listener_retry_at:
                    listener_retry_at = time.monotonic() + 5
                    try:
                        listener = store.work_listener()
                    except Exception:
                        log.warning('Wake-up listener unavailable; durable polling retained')
                if listener is not None:
                    try:
                        store.drain_work_notifications(listener)
                    except Exception:
                        listener.close(); listener = None
                worked = process_one(store)
                notify_one(store, os.getenv("DISPATCHER_COMPLETION_URL"))
                if not worked:
                    if listener is not None:
                        try:
                            store.wait_for_work(listener)
                        except Exception:
                            listener.close(); listener = None
                            stop.wait(.5)
                    else:
                        stop.wait(.5)
            except Exception:
                if listener is not None:
                    listener.close(); listener = None
                log.exception("Worker paused after queue/processing failure; pending jobs remain durable")
                stop.wait(2)
    finally:
        if listener is not None:
            listener.close()


if __name__ == "__main__":
    main()
