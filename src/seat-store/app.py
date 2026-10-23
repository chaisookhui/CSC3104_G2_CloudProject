"""Module 3 HTTP API. Importing the factory never starts background threads."""

import logging

import psycopg
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from db import Database
from settings import settings
from store import SeatStore, StoreError


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(settings(config))
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    database = app.config.get("DATABASE") or Database(app.config["DATABASE_URL"])
    store = SeatStore(database, app.config["HOLD_TTL_SECONDS"])
    app.extensions["seat_store"] = store

    def body(required, optional=()):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise StoreError("invalid_input", "Expected a JSON object", 400)
        if set(required) - data.keys():
            raise StoreError("invalid_input", "Missing required fields: " +
                             ", ".join(sorted(set(required) - data.keys())), 400)
        if data.keys() - set(required) - set(optional):
            raise StoreError("invalid_input", "Unknown request fields", 400)
        for field in optional:
            if field in data and data[field] is None:
                raise StoreError("invalid_input", f"{field} cannot be null when provided", 400)
        return data

    @app.get("/health")
    def health():
        with database.connect() as conn:
            count = conn.execute("SELECT count(*) AS n FROM sections").fetchone()["n"]
        if count != 4:
            raise StoreError("not_initialized", "Initialize the database before serving", 503)
        return jsonify({"status": "ok", "service": "seat-store", "storage": "postgresql"})

    @app.get("/seats/<section>")
    def seats(section):
        return jsonify(store.list_seats(section))

    @app.get("/holds/<hold_id>")
    def hold_status(hold_id):
        return jsonify(store.get_hold(request.args.get("request_id"), hold_id))

    @app.post("/seats/hold")
    def hold():
        data = body(("section", "party_size", "request_id"), ("reoffer_key",))
        result = store.hold(**data)
        if result["success"]:
            app.logger.info("hold request_id=%s hold_id=%s status=%s", result["request_id"],
                            result["hold_id"], result["hold_status"])
        return jsonify(result)

    def transition(action):
        data = body(("request_id",), ("hold_id",))
        result = store.transition(action=action, **data)
        app.logger.info("%s request_id=%s hold_id=%s", action, result["request_id"], result["hold_id"])
        return jsonify(result)

    @app.post("/seats/confirm")
    def confirm():
        return transition("confirm")

    @app.post("/seats/expire")
    def expire():
        return transition("expire")

    @app.post("/seats/cancel")
    def cancel():
        data = body(("request_id", "hold_id"))
        if data["hold_id"] is None:
            raise StoreError("invalid_input", "hold_id is required", 400)
        return jsonify(store.transition(action="cancel", **data))

    @app.errorhandler(StoreError)
    def domain_error(error):
        return jsonify({"error": error.code, "message": error.message}), error.status

    @app.errorhandler(psycopg.Error)
    def database_error(error):
        app.logger.error("Database operation failed (%s)", type(error).__name__)
        return jsonify({"error": "storage_unavailable",
                        "message": "Booking state could not be verified; retry the same operation"}), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify({"error": error.name.lower().replace(" ", "_"),
                        "message": error.description}), error.code

    return app


if __name__ == "__main__":
    from workers import BackgroundTasks

    logging.basicConfig(level=logging.INFO)
    application = create_app()
    # Fail before accepting requests if schema/storage is not ready.
    application.extensions["seat_store"].db.seed(application.config["SEAT_MAP_TIER"])
    tasks = BackgroundTasks(application.extensions["seat_store"], application.config).start()
    try:
        application.run(host=application.config["HOST"], port=application.config["PORT"],
                        debug=False, use_reloader=False)
    finally:
        tasks.stop()

