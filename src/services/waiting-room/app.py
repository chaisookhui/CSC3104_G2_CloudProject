"""Global registration/queue service. Section scheduling belongs to the dispatcher."""
from datetime import datetime, timezone
import os
import random
import uuid

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from admission_control import AdmissionController
from queue_store import MemoryStore, RedisStore


def create_app(store=None):
    app = Flask(__name__)
    # Keep curl responses readable even when Flask debug mode is disabled.
    app.json.compact = False
    app.json.sort_keys = False
    sections = tuple(os.getenv("SECTIONS", "A,B,C,D").split(","))
    if store is None:
        url = os.getenv("REDIS_URL")
        store = RedisStore(url, os.getenv("QUEUE_KEY", "ticketing:default:queue")) if url else MemoryStore()
    app.extensions["queue_store"] = store
    controller = AdmissionController(window_seconds=10, low_threshold=20,
                                     high_threshold=50, max_admissions_per_second=5)

    @app.errorhandler(Exception)
    def handle_error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        app.logger.exception("Queue operation failed")
        return jsonify(error="Queue unavailable; retry later"), 503

    def request_response(party):
        # Older Redis records may still contain the retired aliases.
        return {key: value for key, value in party.items()
                if key not in ("batch_order", "global_position")}

    @app.post("/submit")
    @app.post("/waiting-room")
    def submit():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Invalid JSON body"), 400
        section, size, user = data.get("section"), data.get("party_size"), data.get("user_id")
        if not isinstance(section, str) or section not in sections:
            return jsonify(error="Invalid section"), 400
        if type(size) is not int or not 1 <= size <= 4:
            return jsonify(error="Party size must be 1-4"), 400
        if not isinstance(user, str) or not user.strip():
            return jsonify(error="Invalid user ID"), 400
        user = user.strip()
        request_id = str(uuid.uuid4())

        def register(state):
            # Repeated submissions return the existing active entry and position.
            if user in state["users"]:
                return state["requests"][state["users"][user]], 200
            party = {"request_id": request_id, "user_id": user, "section": section,
                     "party_size": size, "timestamp": datetime.now(timezone.utc).isoformat(),
                     "entry_type": "waiting_room", "queue_number": None,
                     "status": "REGISTERED"}
            if state["sale_state"] == "sale_started":
                number = state["next_number"]
                state["next_number"] += 1
                party.update(entry_type="latecomer", queue_number=number,
                             status="QUEUED")
                state["queue"].append(request_id)
            state["requests"][request_id] = party
            state["users"][user] = request_id
            return party, 201

        party, code = store.update(register)
        controller.record_request()  # Local telemetry; never limits registration.
        return jsonify(request_response(party)), code

    @app.post("/sale/start")
    def start_sale():
        def open_sale(state):
            if state["sale_state"] == "pre_sale":
                ids = list(state["requests"])
                random.SystemRandom().shuffle(ids)  # Across ALL sections and sizes.
                for number, rid in enumerate(ids, 1):
                    state["requests"][rid].update(queue_number=number,
                        status="QUEUED")
                state["queue"] = ids
                state["next_number"] = len(ids) + 1
                state["sale_state"] = "sale_started"
            return {"sale_state": state["sale_state"], "initial_count": sum(
                r["entry_type"] == "waiting_room" for r in state["requests"].values()),
                "next_queue_number": state["next_number"]}
        return jsonify(store.update(open_sale))

    @app.get("/queue")
    def display_queue():
        state = store.read()
        if state["sale_state"] == "pre_sale":
            parties = list(state["requests"].values())
        else:
            parties = [state["requests"][rid] for rid in state["queue"]]
        return jsonify(sale_state=state["sale_state"], count=len(parties),
                       requests=[request_response(party) for party in parties])

    # changed by zxian
    
    @app.post("/queue/claim")
    def claim_queue():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify(error="Invalid JSON"), 400

        batch_id = data.get("batch_id")
        request_ids = data.get("request_ids")

        if not isinstance(batch_id, str) or not batch_id:
            return jsonify(error="Invalid batch ID"), 400

        if (
            not isinstance(request_ids, list)
            or not request_ids
            or any(
                not isinstance(rid, str) or not rid
                for rid in request_ids
            )
            or len(request_ids) != len(set(request_ids))
        ):
            return jsonify(error="Invalid request IDs"), 400

        
        def claim(state):
            if state["sale_state"] != "sale_started":
                return {"error": "Sale has not started"}, 409

            # Idempotent retry: same requests, same batch.
            already_claimed = all(
                rid in state["requests"]
                and state["requests"][rid]["status"] == "ADMITTED"
                and state["requests"][rid].get("batch_id") == batch_id
                for rid in request_ids
            )

            if already_claimed:
                return {
                    "message": "Batch already claimed",
                    "batch_id": batch_id,
                    "claimed_count": len(request_ids)
                }, 200

            # All requests must currently be eligible.
            for rid in request_ids:
                party = state["requests"].get(rid)

                if party is None:
                    return {
                        "error": f"Unknown request: {rid}"
                    }, 404

                if party["status"] != "QUEUED":
                    return {
                        "error": f"Request not claimable: {rid}"
                    }, 409

            # Get earliest eligible requests in global order.
            eligible_ids = [
                rid for rid in state["queue"]
                if state["requests"][rid]["status"] == "QUEUED"
            ]

            expected_ids = eligible_ids[:len(request_ids)]

            if set(request_ids) != set(expected_ids):
                return {
                    "error": "Requests are not the next eligible global positions",
                    "expected_request_ids": expected_ids
                }, 409

            # Claim the entire batch.
            for rid in request_ids:
                state["requests"][rid].update(
                    status="ADMITTED",
                    batch_id=batch_id
                )

            return {
                "message": "Batch requests claimed",
                "batch_id": batch_id,
                "claimed_count": len(request_ids)
            }, 200

        result, code = store.update(claim)
        return jsonify(result), code

    
    @app.post("/queue/requeue")
    def requeue_requests():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify(error="Invalid JSON"), 400

        batch_id = data.get("batch_id")
        request_ids = data.get("request_ids")

        if not isinstance(batch_id, str) or not batch_id:
            return jsonify(error="Invalid batch ID"), 400

        if (
            not isinstance(request_ids, list)
            or any(
                not isinstance(rid, str) or not rid
                for rid in request_ids
            )
            or len(request_ids) != len(set(request_ids))
        ):
            return jsonify(error="Invalid request IDs"), 400

        def requeue(state):
            for rid in request_ids:
                party = state["requests"].get(rid)

                if party is None:
                    return {
                        "error": f"Unknown request: {rid}"
                    }, 404

                same_batch_admitted = (
                    party["status"] == "ADMITTED"
                    and party.get("batch_id") == batch_id
                )

                already_requeued = (
                    party["status"] == "QUEUED"
                    and party.get("last_batch_id") == batch_id
                )

                if not (
                    same_batch_admitted
                    or already_requeued
                ):
                    return {
                        "error": f"Request not requeueable: {rid}"
                    }, 409

            for rid in request_ids:
                party = state["requests"][rid]

                if party["status"] == "ADMITTED":
                    party.update(
                        status="QUEUED",
                        last_batch_id=batch_id
                    )
                    party.pop("batch_id", None)

                # queue_number is deliberately unchanged.

            return {
                "message": "Requests requeued",
                "batch_id": batch_id,
                "requeued_count": len(request_ids)
            }, 200

        result, code = store.update(requeue)
        return jsonify(result), code

    
    @app.post("/queue/complete")
    def complete_requests():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify(error="Invalid JSON"), 400

        batch_id = data.get("batch_id")
        request_ids = data.get("request_ids")

        if not isinstance(batch_id, str) or not batch_id:
            return jsonify(error="Invalid batch ID"), 400

        if (
            not isinstance(request_ids, list)
            or any(
                not isinstance(rid, str) or not rid
                for rid in request_ids
            )
            or len(request_ids) != len(set(request_ids))
        ):
            return jsonify(error="Invalid request IDs"), 400

        def complete(state):
            for rid in request_ids:
                party = state["requests"].get(rid)

                if party is None:
                    return {
                        "error": f"Unknown request: {rid}"
                    }, 404

                if not (
                    party["status"] == "ADMITTED"
                    and party.get("batch_id") == batch_id
                ) and not (
                    party["status"] == "ALLOCATION_DONE"
                    and party.get("last_batch_id") == batch_id
                ):
                    return {
                        "error": f"Invalid completion: {rid}"
                    }, 409

            for rid in request_ids:
                party = state["requests"][rid]

                if party["status"] == "ADMITTED":
                    party.update(
                        status="ALLOCATION_DONE",
                        last_batch_id=batch_id
                    )
                    party.pop("batch_id", None)

            return {
                "batch_id": batch_id,
                "completed_count": len(request_ids),
                "message": "Allocation statuses updated"
            }, 200

        result, code = store.update(complete)
        return jsonify(result), code


    @app.get("/requests/<request_id>")
    @app.get("/queue/<request_id>")
    def lookup(request_id):
        party = store.read()["requests"].get(request_id)
        return (jsonify(request_response(party)), 200) if party else (jsonify(error="Request not found"), 404)

    @app.get("/status")
    def status():
        state = store.read()
        parties = list(state["requests"].values())
        return jsonify(sale_state=state["sale_state"],
            storage="redis" if isinstance(store, RedisStore) else "memory",
            waiting_count=sum(p["entry_type"] == "waiting_room" for p in parties),
            latecomer_count=sum(p["entry_type"] == "latecomer" for p in parties),
            queued_count=sum(p["status"] == "QUEUED" for p in parties),
            next_queue_number=state["next_number"],
            sections={s: {"registered_count": sum(p["section"] == s for p in parties)} for s in sections},
            load_signal_scope="this_pod", registration_limited=False,
            admission_policy="external_dispatcher", **controller.get_status())

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/ready")
    def ready():
        store.read()
        return jsonify(status="ready")

    return app


app = create_app()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
