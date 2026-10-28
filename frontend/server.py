"""Demo frontend: serves the static page and forwards /api/<service>/... to the services."""
import os

import requests
from flask import Flask, Response, abort, request

# Service addresses come from the environment so the same code runs in a container.
SERVICES = {
    "waiting-room": os.getenv("WAITING_ROOM_URL", "http://127.0.0.1:5001"),
    "allocation": os.getenv("ALLOCATION_URL", "http://127.0.0.1:5002"),
    "seats": os.getenv("SEAT_STORE_URL", "http://127.0.0.1:5003"),
    "payment": os.getenv("PAYMENT_URL", "http://127.0.0.1:5004"),
    "dispatcher": os.getenv("DISPATCHER_URL", "http://127.0.0.1:5005"),
}


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="")
    payment_token = os.getenv("PAYMENT_API_TOKEN", "")

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.route("/api/<service>/<path:path>", methods=["GET", "POST"])
    def forward(service, path):
        base = SERVICES.get(service)
        if base is None:
            abort(404)
        headers = {"Content-Type": "application/json"}
        # The internal token is added here so it never reaches browser code.
        if service == "payment" and payment_token:
            headers["Authorization"] = "Bearer " + payment_token
        try:
            upstream = requests.request(
                request.method, f"{base.rstrip('/')}/{path}", params=request.args,
                data=request.get_data() or None, headers=headers, timeout=10,
                allow_redirects=False)
        except requests.RequestException:
            return {"error": f"{service} service is not reachable"}, 502
        return Response(upstream.content, upstream.status_code,
                        content_type=upstream.headers.get("Content-Type", "application/json"))

    return app


if __name__ == "__main__":
    create_app().run(host=os.getenv("FRONTEND_HOST", "127.0.0.1"),
                     port=int(os.getenv("FRONTEND_PORT", "8080")))
