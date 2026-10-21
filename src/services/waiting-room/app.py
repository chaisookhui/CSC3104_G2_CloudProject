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
