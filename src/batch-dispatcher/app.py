import os
from threading import RLock

import requests
from flask import Flask, jsonify

from dispatcher_logic import BatchDispatcher, parse_waiting_room_queue

app = Flask(__name__)
app.json.sort_keys = False

WAITING_ROOM_URL = os.getenv("WAITING_ROOM_URL", "http://localhost:5001").rstrip("/")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))

lock = RLock()
dispatcher = BatchDispatcher(batch_size=BATCH_SIZE)
active_batch = None
active_requests = []
batch_history = []


def fetch_global_queue():
    response = requests.get(f"{WAITING_ROOM_URL}/queue", timeout=5)
    response.raise_for_status()
    return parse_waiting_room_queue(response.json())


def update_waiting_room(endpoint, batch_id, request_ids):
    if not request_ids:
        return None
    response = requests.post(
        f"{WAITING_ROOM_URL}{endpoint}",
        json={"batch_id": batch_id, "request_ids": request_ids},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def allocator_preview(payload):
    """Unranked per-section, per-party-size input for Part 5. NO network send."""
    return {
        "batch_id": payload["batch_id"],
        "batch_size": payload["batch_size"],
        "sections": payload["sections"],
    }


@app.post("/batches/next")
def next_batch():
    global active_batch, active_requests
    # Keep the preview operation serialised for this single-process prototype.
    with lock:
        if active_batch is not None:
            return jsonify(error="Current batch is still active", batch_id=active_batch["batch_id"]), 409
        try:
            records = fetch_global_queue()
        except ValueError as exc:
            return jsonify(error=str(exc)), 409
        except requests.RequestException as exc:
            return jsonify(error="Waiting Room unavailable", details=str(exc)), 503

        dispatcher.update_queue(records)
        result = dispatcher.create_next_batch()
        if result is None:
            return jsonify(message="No eligible queued requests"), 200
        payload, snapshot = result
        active_batch, active_requests = payload, snapshot
        batch_history.append({"batch_id": payload["batch_id"], "state": "CLAIMING", "batch_size": payload["batch_size"]})

        try:
            update_waiting_room(
                "/queue/claim", payload["batch_id"],
                [r.request_id for r in snapshot],
            )
        except requests.HTTPError as exc:
            # A definitive HTTP rejection: this attempt should not be treated as claimed.
            if exc.response is not None and exc.response.status_code in (400, 404, 409):
                dispatcher.finish_preview(snapshot)
                active_batch, active_requests = None, []
                batch_history[-1]["state"] = "CLAIM_REJECTED"
                return jsonify(error="Waiting Room rejected claim", details=exc.response.text), 409
            batch_history[-1]["state"] = "CLAIM_UNCERTAIN"
            return jsonify(error="Claim outcome uncertain; inspect Waiting Room", details=str(exc)), 503
        except requests.RequestException as exc:
            batch_history[-1]["state"] = "CLAIM_UNCERTAIN"
            return jsonify(error="Claim outcome uncertain; inspect Waiting Room", details=str(exc)), 503

        batch_history[-1]["state"] = "PREVIEW_READY"
        return jsonify({
            "message": "Batch claimed; preview ready; NOT sent to allocator",
            "batch_id": payload["batch_id"],
            "batch_size": payload["batch_size"],
            "allocator_input_url": "/batches/allocator-input",
        }), 200


@app.get("/batches/current")
def current_batch():
    with lock:
        return jsonify(active_batch if active_batch else {"message": "No active batch"})


@app.get("/batches/allocator-input")
def get_allocator_input():
    with lock:
        if active_batch is None:
            return jsonify(error="No active batch"), 404
        return jsonify(allocator_preview(active_batch))


@app.get("/status")
def status():
    with lock:
        return jsonify({
            "waiting_room_url": WAITING_ROOM_URL,
            "batch_size": dispatcher.batch_size,
            "active_batch_id": active_batch["batch_id"] if active_batch else None,
            "last_known_remaining": dispatcher.remaining_count(),
            "handoff": "preview_only_no_allocator_call",
            "batch_history": batch_history,
        })


@app.post("/batches/<batch_id>/finish-preview")
def finish_preview(batch_id):
    """TEST ONLY: simulate completed allocation so batch 2 can be demonstrated.

    No allocator connection and no seat reservation happens. This deliberately
    changes Part 2 QUEUE statuses to ALLOCATION_DONE for the previewed requests.
    """
    global active_batch, active_requests
    with lock:
        if active_batch is None or active_batch["batch_id"] != batch_id:
            return jsonify(error="No matching active batch"), 404
        try:
            update_waiting_room(
                "/queue/complete", batch_id,
                [r.request_id for r in active_requests],
            )
        except requests.RequestException as exc:
            batch_history[-1]["state"] = "PREVIEW_COMPLETION_UNCERTAIN"
            return jsonify(error="Waiting Room completion failed", details=str(exc)), 503

        dispatcher.finish_preview(active_requests)
        batch_history[-1]["state"] = "PREVIEW_FINISHED_TEST_ONLY"
        active_batch, active_requests = None, []
        return jsonify(message="Test-only preview finished; NO seats allocated", batch_id=batch_id), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
