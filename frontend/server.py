"""Demo frontend: serves the static page and forwards /api/<service>/... to the services."""
import os

import requests
from flask import Flask, Response, abort, request
try:
    from frontend.access import install_access
except ModuleNotFoundError:
    from access import install_access

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
    install_access(app,SERVICES,payment_token)

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get('/api/demo/context')
    def demo_context():
        namespace = os.getenv('EXPERIMENT_NAMESPACE', 'local-or-compose')
        return {'namespace': namespace, 'is_lab': namespace in ('csc3104-lab', 'csc3104-check'),
                'authentication': 'browser ownership and administrator access' if app.config['ACCESS_ENABLED'] else 'demo identities only; no trusted login'}

    if not app.config['ACCESS_ENABLED']:
        @app.get('/api/session')
        def disabled_session():
            return {'enabled':False,'admin':True,'users':[]}

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
        if service=='waiting-room' and path=='queue' and upstream.status_code==200 and app.config['ACCESS_ENABLED']:
            return app.extensions['filter_customer_queue'](upstream.json())
        response=Response(upstream.content, upstream.status_code,
                        content_type=upstream.headers.get("Content-Type", "application/json"))
        if upstream.headers.get('X-Service-Instance'):
            response.headers['X-Service-Instance']=upstream.headers['X-Service-Instance']
        return response

    return app


if __name__ == "__main__":
    create_app().run(host=os.getenv("FRONTEND_HOST", "127.0.0.1"),
                     port=int(os.getenv("FRONTEND_PORT", "8080")))
