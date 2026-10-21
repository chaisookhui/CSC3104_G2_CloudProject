import os
from threading import RLock

import requests
from flask import Flask, jsonify, request

from dispatcher_logic import (
    BatchDispatcher,
    parse_waiting_room_queue,
    build_allocator_payload
)

app = Flask(__name__)
app.json.sort_keys = False

# these can move to .env further down the project (cleaning stage)
WAITING_ROOM_URL = os.getenv("WAITING_ROOM_URL", "http://localhost:5001").rstrip("/")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))
ALLOCATOR_URL = os.getenv("ALLOCATOR_URL","http://localhost:5002").rstrip("/")

lock = RLock()
dispatcher = BatchDispatcher(batch_size=BATCH_SIZE)
active_batch = None
active_requests = []
batch_history = []
processed_events = {}
batch_state = None


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


def send_to_allocator(payload):
    """
    Submit a fixed batch using Part 5's actual API format.
    """
    allocator_payload = build_allocator_payload(payload)

    response = requests.post(
        f"{ALLOCATOR_URL}/batches",
        json=allocator_payload,
        timeout=5
    )

    response.raise_for_status()

    if response.status_code not in (200, 202):
        raise ValueError("Unexpected allocator response")

    result = response.json()

    if result.get("batch_id") != payload["batch_id"]:
        raise ValueError("Allocator returned wrong batch ID")

    return result


def fetch_allocator_results(batch_id):
    response = requests.get(
        f"{ALLOCATOR_URL}/batches/{batch_id}",
        timeout=5
    )
    response.raise_for_status()
    return response.json()


def update_waiting_room_outcomes(batch_id, outcomes):
    response = requests.post(
        f"{WAITING_ROOM_URL}/queue/outcomes",
        json={
            "batch_id": batch_id,
            "outcomes": outcomes
        },
        timeout=5
    )
    response.raise_for_status()
    return response.json()



@app.post("/batches/next")
def next_batch():
    global active_batch, active_requests, batch_state

    with lock:
        if active_batch is not None:
            return jsonify(
                error="Current batch is still active",
                batch_id=active_batch["batch_id"]
            ), 409

        try:
            records = fetch_global_queue()
        except ValueError as error:
            return jsonify(error=str(error)), 409
        except requests.RequestException as error:
            return jsonify(
                error="Waiting Room unavailable",
                details=str(error)
            ), 503

        dispatcher.update_queue(records)

        result = dispatcher.create_next_batch()

        if result is None:
            batch_state = "QUEUE_EMPTY"
            return jsonify(
                message="No eligible queued requests"
            ), 200

        payload, snapshot = result
        active_batch = payload
        active_requests = snapshot
        batch_state = "CLAIMING"

        batch_history.append({
            "batch_id": payload["batch_id"],
            "batch_size": payload["batch_size"],
            "state": "CLAIMING",
            "allocator_input": build_allocator_payload(payload)
        })

        try:
            update_waiting_room(
                "/queue/claim",
                payload["batch_id"],
                [r.request_id for r in snapshot]
            )

        except requests.RequestException as error:
            batch_state = "CLAIM_UNCERTAIN"
            batch_history[-1]["state"] = batch_state

            return jsonify(
                error="Waiting Room claim failed or uncertain",
                batch_id=payload["batch_id"],
                details=str(error)
            ), 503

        batch_state = "SUBMITTING"
        batch_history[-1]["state"] = batch_state

        try:
            allocation_response = send_to_allocator(payload)

        except (requests.RequestException, ValueError) as error:
            # It is unsafe to create another batch here:
            # the allocator may have accepted this request.
            batch_state = "SUBMISSION_UNCERTAIN"
            batch_history[-1]["state"] = batch_state

            return jsonify(
                error="Allocator submission failed or uncertain",
                batch_id=payload["batch_id"],
                details=str(error)
            ), 503

        batch_state = "WAITING_FOR_ALLOCATION"
        batch_history[-1]["state"] = batch_state

        return jsonify({
            "message": "Batch accepted by allocator",
            "batch_id": payload["batch_id"],
            "batch_size": payload["batch_size"],
            "allocator_response": allocation_response
        }), 202


@app.post("/allocator/status")
def allocator_status():
    global active_batch, active_requests, batch_state

    event = request.get_json(silent=True)

    if not isinstance(event, dict):
        return jsonify(error="Invalid event"), 400

    event_id = event.get("event_id")
    batch_id = event.get("batch_id")

    if (
        not isinstance(event_id, str) or not event_id
        or not isinstance(batch_id, str) or not batch_id
        or event.get("type") != "batch.allocation_completed"
    ):
        return jsonify(error="Invalid completion event"), 400

    with lock:
        # Exact duplicate event: acknowledge without advancing.
        if event_id in processed_events:
            if processed_events[event_id] != event:
                return jsonify(error="Conflicting event ID"), 409

            return jsonify(
                message="Duplicate event acknowledged",
                batch_id=batch_id
            ), 200

        if (
            active_batch is None
            or active_batch["batch_id"] != batch_id
        ):
            return jsonify(error="Unknown active batch"), 409

        if batch_state not in (
            "SUBMITTING",
            "SUBMISSION_UNCERTAIN",
            "WAITING_FOR_ALLOCATION",
            "RESULT_FETCH_FAILED",
            "OUTCOME_SYNC_FAILED"
        ):
            return jsonify(
                error="Batch not ready for completion",
                state=batch_state
            ), 409

        snapshot = list(active_requests)
        expected_ids = {r.request_id for r in snapshot}

        try:
            details = fetch_allocator_results(batch_id)
        except (requests.RequestException, ValueError) as error:
            batch_state = "RESULT_FETCH_FAILED"
            batch_history[-1]["state"] = batch_state
            return jsonify(
                error="Could not fetch allocator results",
                details=str(error)
            ), 503

        jobs = details.get("jobs")

        if (
            details.get("batch_id") != batch_id
            or details.get("complete") is not True
            or not isinstance(jobs, list)
        ):
            return jsonify(error="Allocator batch is not complete"), 409

        actual_ids = [job.get("request_id") for job in jobs
                      if isinstance(job, dict)]

        if (
            len(actual_ids) != len(jobs)
            or len(set(actual_ids)) != len(actual_ids)
            or set(actual_ids) != expected_ids
        ):
            return jsonify(
                error="Allocator request IDs do not match batch"
            ), 409

        counts = {
            "RESERVED": 0,
            "UNAVAILABLE": 0,
            "CANCELLED": 0
        }

        for job in jobs:
            state = job.get("state")
            if state not in counts:
                return jsonify(
                    error="Unexpected allocation state",
                    state=state
                ), 409
            counts[state] += 1

        # CANCELLED needs its own agreed Waiting Room policy.
        # Reject instead of silently mapping it to UNAVAILABLE.
        if counts["CANCELLED"]:
            return jsonify(
                error="CANCELLED handling not agreed yet"
            ), 409

        if (
            event.get("total_requests") != len(jobs)
            or event.get("outcomes") != counts
        ):
            return jsonify(
                error="Completion event counts do not match jobs"
            ), 409

        outcomes = [
            {
                "request_id": job["request_id"],
                "status": job["state"]
            }
            for job in jobs
        ]

        batch_state = "SYNCING_OUTCOMES"
        batch_history[-1]["state"] = batch_state

        try:
            update_waiting_room_outcomes(batch_id, outcomes)
        except requests.RequestException as error:
            batch_state = "OUTCOME_SYNC_FAILED"
            batch_history[-1]["state"] = batch_state
            return jsonify(
                error="Waiting Room outcome sync failed",
                details=str(error)
            ), 503

        dispatcher.finish_batch(snapshot)

        batch_history[-1]["state"] = "COMPLETED"
        batch_history[-1]["outcomes"] = counts

        processed_events[event_id] = dict(event)

        active_batch = None
        active_requests = []
        batch_state = "COMPLETED"

    # IMPORTANT: outside the lock.
    # Only after Waiting Room accepted all outcomes.
    next_response = app.test_client().post("/batches/next")

    return jsonify({
        "message": "Batch completed; next batch attempted",
        "batch_id": batch_id,
        "outcomes": counts,
        "next_batch_http_status": next_response.status_code,
        "next_batch": next_response.get_json()
    }), 200


@app.get("/batches/current")
def current_batch():
    with lock:
        return jsonify(active_batch if active_batch else {"message": "No active batch"})

# for debugging
@app.get("/batches/allocator-input")
def get_allocator_input():
    with lock:
        if active_batch is None:
            return jsonify(error="No active batch"), 404

        return jsonify(build_allocator_payload(active_batch))


@app.get("/status")
def status():
    with lock:
        return jsonify({
            "waiting_room_url": WAITING_ROOM_URL,
            "allocator_url": ALLOCATOR_URL,
            "batch_size": dispatcher.batch_size,
            "active_batch_id": (
                active_batch["batch_id"]
                if active_batch else None
            ),
            "batch_state": batch_state,
            "last_known_remaining": dispatcher.remaining_count(),
            "batch_history": batch_history
        })

# stored in memory, reset one dispatcher process restarts
@app.get("/batches/history")
def get_batch_history():
    with lock:
        return jsonify({
            "total_batches": len(batch_history),
            "active_batch_id": (
                active_batch["batch_id"]
                if active_batch else None
            ),
            "history": batch_history
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
