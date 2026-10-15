
from flask import Flask, request, jsonify
from datetime import datetime, timezone
from threading import Lock, Thread
from copy import deepcopy
import uuid
import os
import requests
import random
from admission_control import AdmissionController

app = Flask(__name__)
app.config["ALLOCATOR_URL"] = os.getenv("ALLOCATOR_URL", "http://localhost:5002").rstrip("/")
app.config["ALLOCATOR_TIMEOUT"] = float(os.getenv("ALLOCATOR_TIMEOUT", "10"))

sale_state = "pre_sale"
initial_batch = None
waiting_room_lock = Lock()
batch_delivery = {}
allocation_results = {}
# Next number per (section, party_size), continuing after the randomized batch.
next_queue_numbers = {}

# Temporary sitting sections
waiting_room = {
    "A": [],
    "B": [],
    "C": []
}

# Retain latecomer requests after delivery for counts and retry tracking.
latecomer_queues = {section: [] for section in waiting_room}
latecomer_delivery = {}
latecomer_results = {}
latecomer_workers = set()


def forward_latecomers(section):
    """One worker per section sends requests in queue order, stopping on failure."""
    while True:
        with waiting_room_lock:
            pending = next((r for r in latecomer_queues[section]
                            if latecomer_delivery[r["request_id"]] != "sent"), None)
            if pending is None:
                latecomer_workers.discard(section)
                return
            party = deepcopy(pending)
            request_id = party["request_id"]
            latecomer_delivery[request_id] = "sending"

        try:
            response = requests.post(
                f"{app.config['ALLOCATOR_URL']}/allocate/{section}",
                json=[party], timeout=app.config["ALLOCATOR_TIMEOUT"]
            )
            response.raise_for_status()
            results = response.json()
            if not isinstance(results, list):
                raise ValueError("Allocator response must be a list")
        except (requests.RequestException, ValueError) as exc:
            app.logger.warning("Latecomer delivery failed for %s: %s", request_id, exc)
            with waiting_room_lock:
                latecomer_delivery[request_id] = "failed"
                latecomer_workers.discard(section)
            return

        with waiting_room_lock:
            latecomer_results[request_id] = results
            latecomer_delivery[request_id] = "sent"


def start_latecomer_worker(section):
    """Called with waiting_room_lock held; initial batch must finish first."""
    if (batch_delivery.get(section) in ("sent", "empty")
            and section not in latecomer_workers
            and any(latecomer_delivery[r["request_id"]] != "sent"
                    for r in latecomer_queues[section])):
        latecomer_workers.add(section)
        Thread(target=forward_latecomers, args=(section,), daemon=True).start()


@app.route("/latecomers/retry", methods=["POST"])
def retry_latecomers():
    with waiting_room_lock:
        for section in latecomer_queues:
            start_latecomer_worker(section)
        return jsonify({"latecomer_delivery": dict(latecomer_delivery)}), 202
admission_controller = AdmissionController(
    window_seconds=10,
    low_threshold=20,
    high_threshold=50,
    max_admissions_per_second=5
)

@app.route("/submit", methods=["POST"])
def submit_request():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    section = data.get("section")
    party_size = data.get("party_size")
    user_id = data.get("user_id")

    if not isinstance(section, str) or section not in waiting_room:
        return jsonify({"error": "Invalid section"}), 400

    if type(party_size) is not int or not 1 <= party_size <= 4:
        return jsonify({"error": "Party size must be 1-4"}), 400

    if not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"error": "Invalid user ID"}), 400

    admission_controller.record_request()

    new_request = {
        "request_id": str(uuid.uuid4()),
        "user_id": user_id,
        "section": section,
        "party_size": party_size,
        "entry_type": "waiting_room",
        "batch_order": None,
        "queue_number": None
    }

    with waiting_room_lock:
        # Assign the timestamp at enqueue time so concurrent submissions have
        # the same ordering in the timestamp and queue.
        new_request["timestamp"] = datetime.now(timezone.utc).isoformat()
        if sale_state == "pre_sale":
            waiting_room[section].append(new_request)
        else:
            new_request["entry_type"] = "latecomer"
            group_key = (section, party_size)
            new_request["queue_number"] = next_queue_numbers[group_key]
            next_queue_numbers[group_key] += 1
            latecomer_queues[section].append(new_request)
            latecomer_delivery[new_request["request_id"]] = "pending"
            start_latecomer_worker(section)

        # Copy before releasing the lock: sale start may assign numbers next.
        payload = deepcopy(new_request)
    return jsonify(payload), 201


@app.route("/requests/<request_id>", methods=["GET"])
def get_request(request_id):
    """Let waiting-room users retrieve their number after sale start."""
    with waiting_room_lock:
        for queues in (waiting_room, latecomer_queues):
            for queue in queues.values():
                for party in queue:
                    if party["request_id"] == request_id:
                        return jsonify(party), 200
    return jsonify({"error": "Request not found"}), 404


@app.route("/status", methods=["GET"])
def get_status():
    admission_status = admission_controller.get_status()
    with waiting_room_lock:
        waiting_by_section = {
            section: len(queue) for section, queue in waiting_room.items()
        }
        latecomers_by_section = {
            section: len(queue) for section, queue in latecomer_queues.items()
        }
        return jsonify({
            # Counts the collected initial requests, including delivered batches.
            "waiting_count": sum(waiting_by_section.values()),
            "waiting_count_by_section": waiting_by_section,
            "latecomer_count": sum(latecomers_by_section.values()),
            "latecomer_count_by_section": latecomers_by_section,
            "latecomer_delivery": dict(latecomer_delivery),
            "latecomer_results": deepcopy(latecomer_results),
            "sale_state": sale_state,
            "batch_delivery": dict(batch_delivery),
            **admission_status
        })


# Manual development trigger until sale scheduling is implemented.
@app.route("/sale/start", methods=["POST"])
def start_sale():
    global sale_state, initial_batch

    with waiting_room_lock:
        if sale_state == "pre_sale":
            # Randomize only within each section/party-size group, exactly once.
            # The allocator must honor batch_order rather than shuffle again.
            for section, queue in waiting_room.items():
                for size in range(1, 5):
                    group = [party for party in queue if party["party_size"] == size]
                    random.SystemRandom().shuffle(group)
                    for number, party in enumerate(group, start=1):
                        party["queue_number"] = number
                        party["batch_order"] = number
                    next_queue_numbers[(section, size)] = len(group) + 1
            # Freeze the section batches once, before closing the waiting room.
            # Use independent copies for the later allocator handoff.
            initial_batch = deepcopy(waiting_room)
            sale_state = "sale_started"
            batch_delivery.update({
                section: "pending" if queue else "empty"
                for section, queue in initial_batch.items()
            })

        # Claim pending sections so concurrent sale-start calls cannot resend them.
        batches_to_send = {}
        for section, state in batch_delivery.items():
            if state in ("pending", "failed"):
                batch_delivery[section] = "sending"
                batches_to_send[section] = deepcopy(initial_batch[section])

    errors = {}
    # Network calls run outside the lock so /submit and /status stay responsive.
    for section, batch in batches_to_send.items():
        try:
            response = requests.post(
                f"{app.config['ALLOCATOR_URL']}/allocate/{section}",
                json=batch,
                timeout=app.config["ALLOCATOR_TIMEOUT"]
            )
            response.raise_for_status()
            results = response.json()
            if not isinstance(results, list):
                raise ValueError("Allocator response must be a list")
            with waiting_room_lock:
                allocation_results[section] = results
                batch_delivery[section] = "sent"
        except (requests.RequestException, ValueError) as exc:
            app.logger.warning("Allocator delivery failed for section %s: %s", section, exc)
            with waiting_room_lock:
                batch_delivery[section] = "failed"
            errors[section] = "Allocator delivery failed; retry POST /sale/start"

    with waiting_room_lock:
        for section in latecomer_queues:
            start_latecomer_worker(section)
        payload = {
            "sale_state": sale_state,
            "batch_counts": {
                section: len(queue)
                for section, queue in initial_batch.items()
            },
            "batch_delivery": dict(batch_delivery),
            "allocation_results": deepcopy(allocation_results),
            "errors": errors
        }
        status_code = 502 if "failed" in batch_delivery.values() else (
            202 if "sending" in batch_delivery.values() else 200
        )
    return jsonify(payload), status_code


if __name__ == "__main__":
    app.run(port=5001, debug=True)
