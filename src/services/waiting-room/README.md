# Waiting room and one global admission queue

Before sale start, `/submit` records section A-D and party size 1-4, with no
registration-count or rate limit. One active registration per supplied user ID is
allowed; a repeated submission returns the original request with HTTP 200.
User IDs are caller supplied in this prototype, not authenticated identities.

`POST /sale/start` atomically shuffles ALL registered requests once. Global
positions 1..N are independent of section and party size. Subsequent requests
append as N+1, N+2, ... in accepted-server order. `queue_number` is the single global-position field, shared across all sections
and party sizes. Repeated sale-start calls never shuffle
again. Original timestamps remain intact.

## Local run and tests

Run from this directory with dependencies installed in your environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Without REDIS_URL, this uses single-process in-memory storage. Never run multiple
processes/Pods with memory mode: each would create its own event and sequence.
From the repository root, run tests:

```sh
python3 -m unittest discover -s src/services/waiting-room/tests -v
```

## Module boundary

The dispatcher claims earliest queued requests with `POST /queue/claim` and
persists allocation outcomes with `POST /queue/outcomes`. These operations are
atomic and idempotent. Outcome records now include `allocation` with hold_id,
hold_status, hold_expiry and seat IDs for checkout discovery. Legacy outcomes
without allocation details remain accepted; discovery can read the allocator batch.

Local service URLs: DISPATCHER_URL defaults to port 5005, ALLOCATOR_URL to 5002,
PAYMENT_URL to 5004. Set reachable service DNS in containers. PAYMENT_API_TOKEN,
if configured, is forwarded to payment. Queue lookup exposes an allocation-stage
snapshot; checkout refresh is authoritative for subsequent payment/expiry status.

| Method | Path | Purpose |
|---|---|---|
| POST | /submit (alias /waiting-room) | Register user_id, section, party_size |
| POST | /sale/start | Shuffle once and attempt initial dispatcher trigger |
| GET | /queue | Queue records for dispatcher |
| GET | /requests/{id} (alias /queue/{id}) | Registration and allocation snapshot |
| GET | /requests/{id}/checkout | Discover exact hold, refresh payment/seat-store state |
| POST | /requests/{id}/cancel | Supply action_key; persist payment cancellation intent |
| POST | /queue/claim, /queue/outcomes | Internal dispatcher mutations |

Checkout can discover a RESERVED job while its batch is still running. Missing
allocation returns 409; unavailable/malformed dependencies return 503 rather than
pretending a checkout exists. Cancellation is asynchronous: poll checkout or the
payment cancellation action until terminal. Payment workers must run.

UNAVAILABLE allocations and expired or cancelled checkouts are exit points. There
is no rejoin or waitlist: submitting again with the same user_id returns the
finished entry. Internal /queue/requeue recovery only retries a dispatcher handoff
and keeps the original queue position.

The dispatcher's periodic worker discovers late arrivals and recovers a
failed sale-start trigger. Run it even when the queue is empty. `queued_count`
counts currently QUEUED entries, while waiting/latecomer counts are historical
registration totals. IDs and user_id remain caller supplied, not authenticated
identities; do not expose these internal APIs as a public authenticated product.

## Kubernetes / shared storage

Set REDIS_URL and the same QUEUE_KEY on ALL queue replicas. Redis WATCH/MULTI
transactions protect registration, duplicate checks, opening cutoff, numbering,
queue updates across processes. Redis errors fail closed with 503;
there is no fallback to a private in-memory queue.

```sh
docker build -t ticketing-waiting-queue:local src/services/waiting-room
# Load that image into your chosen local cluster (kind/minikube as appropriate).
kubectl apply -f infra/k8s/waiting-queue.yaml
kubectl port-forward service/waiting-queue 5001:5001
kubectl get hpa waiting-queue
```

The manifest provides Redis with append-only persistence/PVC, queue Deployment,
Services, health/readiness probes and a CPU HPA (1-5 API Pods). HPA requires the
cluster metrics server and available CPU/memory/storage. It scales API Pods,
not Redis; registration itself has no configured user-count cap. This is not a
guarantee that arbitrary traffic can be accepted by finite resources.

Prototype limitations: the Redis backend serializes one event JSON snapshot on
every mutation and uses optimistic retries. It is correct across replicas but
not a high-throughput queue implementation: large events should use normalized
Redis structures plus durable MySQL records as specified in the final design.
AOF Redis is the current queue persistence; MySQL queue recovery is not yet built.
One Redis instance remains a single point of failure. Real Redis and Kubernetes
integration/load testing are required before claiming horizontal throughput gains.

The existing AdmissionController is retained as per-Pod recent-load telemetry.
Its `full`/`throttled` label DOES NOT reject registrations or change numbering.
Admission and batch processing belong to the external dispatcher.
