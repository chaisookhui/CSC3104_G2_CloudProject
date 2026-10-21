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

This service stops at assigning and storing global queue positions. It does not
claim batches, admit requests, rank demand, forward to allocators or record
allocation outcomes. The dispatcher is owned by a teammate; its handoff contract
will be agreed during integration. `/batches/claim` and batch completion APIs
are not provided.

Endpoints: POST `/submit` (alias `/waiting-room`, requires user_id, section and
party_size), POST `/sale/start`, GET `/requests/<request_id>` (alias
`/queue/<request_id>`), GET `/status`, GET `/health`, GET `/ready`.

`queued_count` counts requests with assigned positions (QUEUED). This module does
not decrement it for downstream processing. `waiting_count` and `latecomer_count`
are registration totals by entry type. Duplicate users retain their existing
entry; closing entries and rejoining require a future integration contract.

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
