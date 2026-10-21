# does not user Workers and SeatStore
# created just to test flow between Allocator, Waiting Room and Dispatcher

# /test/batches/{batch_id}/complete route exists only in mock_allocator.py, not the real allocator.


"""
Mock allocation HTTP service.

Matches the real allocator's:
POST /batches
GET  /batches/<batch_id>
batch.allocation_completed notification

Additional TEST-ONLY route:
POST /test/batches/<batch_id>/complete

No SeatStore calls and no actual seat reservations.
"""

import os
import json
import uuid
from threading import RLock

import requests
from flask import Flask, jsonify, request

from algorithm import prepare_batch

app = Flask(__name__)
app.json.sort_keys = False

DISPATCHER_URL = os.getenv(
    "DISPATCHER_URL",
    "http://localhost:5003"
).rstrip("/")

lock = RLock()
batches = {}


@app.get("/health")
def health():
    return jsonify(status="ok", service="mock-allocation")


@app.post("/batches")
def submit_batch():
    payload = request.get_json(silent=True)

    try:
        orders, jobs = prepare_batch(
            payload,
            sections=("A", "B", "C", "D")
        )
    except (ValueError, TypeError, KeyError) as error:
        return jsonify(error=str(error)), 400

    batch_id = payload["batch_id"]
    canonical = json.dumps(payload, sort_keys=True)

    with lock:
        if batch_id in batches:
            existing = batches[batch_id]

            if existing["canonical"] != canonical:
                return jsonify(
                    error="Batch ID already used with different input"
                ), 409

            return jsonify({
                "batch_id": batch_id,
                "size_order": existing["size_order"],
                "status": "already_accepted"
            }), 200

        # Similar to the real allocator:
        # do not accept a new batch while a previous
        # one has unfinished allocation jobs.
        if any(not record["complete"]
               for record in batches.values()):
            return jsonify(
                error="Previous batch is not complete"
            ), 409

        batches[batch_id] = {
            "canonical": canonical,
            "size_order": orders,
            "jobs": [
                {
                    **job,
                    "state": "QUEUED",
                    "attempts": 0,
                    "result": None,
                    "error": None
                }
                for job in jobs
            ],
            "complete": False,
            "event": None
        }

    return jsonify({
        "batch_id": batch_id,
        "size_order": orders,
        "status": "accepted"
    }), 202


@app.get("/batches/<batch_id>")
def get_batch(batch_id):
    with lock:
        record = batches.get(batch_id)

        if record is None:
            return jsonify(error="Unknown batch"), 404

        return jsonify({
            "batch_id": batch_id,
            "size_order": record["size_order"],
            "complete": record["complete"],
            "jobs": record["jobs"],
            "completion_notification": (
                "not_created"
                if record["event"] is None
                else "pending"
            )
        }), 200


@app.post("/test/batches/<batch_id>/complete")
def complete_test_batch(batch_id):
    """
    Manually complete one mock batch.

    JSON example:
    {"unavailable_count": 10}

    The remaining requests become RESERVED.
    """
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="Expected JSON object"), 400

    unavailable_count = data.get("unavailable_count", 0)

    if (
        type(unavailable_count) is not int
        or unavailable_count < 0
    ):
        return jsonify(error="Invalid unavailable_count"), 400

    with lock:
        record = batches.get(batch_id)

        if record is None:
            return jsonify(error="Unknown batch"), 404

        jobs = record["jobs"]

        if unavailable_count > len(jobs):
            return jsonify(
                error="Unavailable count exceeds batch size"
            ), 400

        if record["complete"]:
            event = record["event"]

            if event["outcomes"]["UNAVAILABLE"] != unavailable_count:
                return jsonify(
                    error="Batch already completed with different results"
                ), 409
        else:
            # Assign UNAVAILABLE to the final N jobs
            # in allocator scheduling order.
            cutoff = len(jobs) - unavailable_count

            for index, job in enumerate(jobs):
                outcome = (
                    "RESERVED"
                    if index < cutoff
                    else "UNAVAILABLE"
                )

                job["state"] = outcome
                job["attempts"] = 1
                job["result"] = {
                    "state": outcome,
                    "success": outcome == "RESERVED"
                }

            record["complete"] = True

            event = {
                "event_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    "allocation-complete:" + batch_id
                )),
                "type": "batch.allocation_completed",
                "batch_id": batch_id,
                "total_requests": len(jobs),
                "outcomes": {
                    "RESERVED": cutoff,
                    "UNAVAILABLE": unavailable_count,
                    "CANCELLED": 0
                }
            }

            record["event"] = event

    # Send notification only after terminal jobs
    # are visible through GET /batches/<id>.
    try:
        response = requests.post(
            f"{DISPATCHER_URL}/allocator/status",
            json=event,
            headers={
                "Idempotency-Key": event["event_id"]
            },
            timeout=10
        )
        response.raise_for_status()

    except requests.RequestException as error:
        return jsonify({
            "message": "Mock batch completed; callback not acknowledged",
            "batch_id": batch_id,
            "error": str(error),
            "retry": "POST this same complete URL again"
        }), 503

    return jsonify({
        "message": "Mock batch completed; dispatcher notified",
        "batch_id": batch_id,
        "outcomes": event["outcomes"],
        "dispatcher_response": response.json()
    }), 200


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5002,
        debug=False,
        use_reloader=False
    )
