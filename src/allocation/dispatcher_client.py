"""Deliver one logical completion event per batch using a durable outbox."""
import logging
import requests

log = logging.getLogger(__name__)


def notify_one(store, url, post=None):
    # No teammate endpoint is assumed. Events remain durable until configured.
    if not url:
        return False
    claim = store.claim_completion()
    if claim is None:
        return False
    try:
        response = (post or requests.post)(
            url, json=claim["payload"],
            headers={"Idempotency-Key": claim["payload"]["event_id"]}, timeout=(3, 5))
        if not 200 <= response.status_code < 300:
            raise requests.RequestException(f"Dispatcher HTTP {response.status_code}")
    except requests.RequestException as exc:
        store.finish_completion(claim, error=str(exc))
        log.warning("Batch completion delivery pending: %s", exc)
    else:
        store.finish_completion(claim)
    return True
