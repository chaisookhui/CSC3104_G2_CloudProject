"""Dispatcher handoff API. Admission and worker execution are separate processes."""
import os
from flask import Flask, jsonify, request

if __package__:
    from .algorithm import prepare_batch
    from .job_store import JobStore, Conflict
else:
    from algorithm import prepare_batch
    from job_store import JobStore, Conflict


def create_app(store=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 128 * 1024
    store = store or JobStore(os.environ["ALLOCATION_DATABASE_URL"])
    app.extensions["allocation_store"] = store
    sections = tuple(os.getenv("ALLOCATION_SECTIONS", "A,B,C").split(","))

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="allocation")

    @app.get("/ready")
    def ready():
        with store.transaction() as execute:
            execute("SELECT id FROM allocation_scheduler WHERE id=1").fetchone()
        return jsonify(status="ready")

    @app.post("/batches")
    def submit():
        payload = request.get_json(silent=True)
        try:
            orders, jobs = prepare_batch(payload, sections=sections)
            created = store.submit(payload, orders, jobs)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Conflict as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(batch_id=payload["batch_id"], size_order=orders,
                       status="accepted" if created else "already_accepted"), 202 if created else 200

    @app.get("/batches/<batch_id>")
    def status(batch_id):
        data = store.batch(batch_id)
        return (jsonify(data), 200) if data else (jsonify(error="Unknown batch"), 404)

    @app.errorhandler(Exception)
    def failure(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.name), exc.code
        app.logger.exception("Allocation storage failure")
        return jsonify(error="Storage unavailable; retry the same batch_id and input"), 503

    return app


if __name__ == "__main__":
    import sys
    store = JobStore(os.environ["ALLOCATION_DATABASE_URL"])
    if sys.argv[1:] == ["init-db"]:
        store.initialize()
    else:
        create_app(store).run(host=os.getenv("HOST", "127.0.0.1"), port=5002, debug=False)
