# Waiting room

Redis is mandatory for deployment. `MemoryStore` exists only for explicit single-process development and unit tests. Both Gunicorn workers and every API Pod use the same `REDIS_URL` and `QUEUE_KEY`. Without `REDIS_URL`, Redis defaults to localhost:6379; memory requires explicit `WAITING_ROOM_STORAGE=memory`. Default API port: **5001**.

## Storage and ordering

The versioned `QUEUE_KEY:v2` namespace contains a metadata hash, user-to-active-request hash, request-record hash, ordered queue zset, lottery zset, and transaction revision. No registration or callback rewrites a queue snapshot. Lua commits duplicate detection, record creation, number allocation and queue insertion together. FCFS means Redis commit order; timestamps are UTC audit fields, not ordering keys. Sections are A–D, party sizes are integers 1–4, and user IDs are trimmed strings of 1–128 characters.

Before opening, each committed registration receives an independent random lottery rank. The first opening commit freezes this set by changing `PRE_SALE` to `OPENING`; later registrations reserve numbers after its known size. The frozen ranks form one stable random permutation. Each opening tick assigns at most 200 initial numbers and saves its cursor atomically. On completion the state becomes `OPEN`. API compatibility names are `pre_sale`, `opening`, and `sale_started`. `/sale/start` returns 202 while numbering continues and 200 once ready. Concurrent starts and recovery ticks cannot reshuffle the frozen group.

The recovery process resumes opening and retries dispatcher ticks every second. Dispatcher ticks persist their batch identity before downstream handoff; run the dispatcher's durable worker too. All dispatcher replicas must share its supported transactional database. Its default local SQLite file must not be copied independently across Pods. Claims are atomic and callbacks reject conflicting outcomes. Dispatcher discovery and claims are blocked until initial numbering finishes.

A repeated `/submit` returns the active attempt, including rejected attempts. `POST /requests/<id>/rejoin` explicitly creates a new attempt at the back after rejection or payment-confirmed expiry/cancellation. The old request ID is its idempotency key; concurrent retries return the same new attempt. Checkout discovery and cancellation remain payment-backed. These prototype APIs still require an authentication layer before public use.

Legacy snapshot deployments: stop **all** old API and dispatcher writers, back up Redis, then run `REDIS_URL=... python tools/migrate_snapshot.py`. It refuses to overwrite v2 data and retains the original snapshot under `QUEUE_KEY:legacy`. New APIs refuse an unmigrated legacy snapshot rather than silently starting a new queue. Do not run old and new writers together.

## Docker verification

From the repository root:

```sh
docker compose -f compose.waiting-room.yaml up -d --build
curl --fail http://localhost:5001/ready
.venv/bin/python -m unittest discover -s src/services/waiting-room/tests -v
docker compose -f compose.waiting-room.yaml exec -T -e TEST_REDIS_URL=redis://redis:6379/15 waiting-room python - < src/services/waiting-room/tests/test_redis.py
.venv/bin/python src/services/waiting-room/tools/smoke.py prepare
docker compose -f compose.waiting-room.yaml restart waiting-room redis
.venv/bin/python src/services/waiting-room/tools/smoke.py verify
```

`smoke.py` adds test users and opens the sale: use an isolated test deployment. Redis uses a named volume and AOF with `appendfsync always`. Do not use `down -v` when retaining queue data. Set `DISPATCHER_URL`, `ALLOCATOR_URL`, and `PAYMENT_URL` to running dependencies; Compose defaults point to ports 5005, 5002 and 5004 on the host. Failed handoffs remain retryable and do not prevent registration.

## Kubernetes verification

Build/load `ticketing-waiting-queue:local` into your test cluster and apply `infra/k8s/waiting-queue.yaml`. It retains the Deployment, Service and CPU HPA (1–5 Pods, 70%), adds a recovery sidecar, and provides requests/limits for API, recovery and persistent Redis. Confirm the `batch-dispatcher`, `allocation`, and `payment-api` Services exist in the same namespace or change their URLs. Configure `PAYMENT_API_TOKEN` from a Secret if payment authentication is enabled. The PVC requires a functioning default StorageClass. This single Redis instance survives replacement via its PVC; it does not provide Redis high availability.

Metrics-server must be installed by your cluster platform. On a Minikube test cluster use `minikube addons enable metrics-server`. Verify metrics before trusting HPA:

```sh
kubectl wait --for=condition=Available apiservice/v1beta1.metrics.k8s.io --timeout=120s
kubectl top pods
kubectl get hpa waiting-queue
kubectl rollout status deployment/waiting-queue
kubectl port-forward service/waiting-queue 5001:5001
```

Run the smoke prepare step, then `kubectl rollout restart deployment/waiting-queue`, wait for rollout completion, and run smoke verify. Repeat after replacing the Redis Pod, checking its PVC remains bound. `/health` is application liveness; `/ready` pings shared Redis and returns 503 on storage failure. Readiness does not depend on payment or dispatcher availability.

## Correctness before scaling

The tests cover duplicate races, opening registrations, stable unique numbers, replacement storage clients resuming chunked opening, competing claims, and idempotent/conflicting outcomes. Dispatcher tests separately cover durable retries after lost responses and lease replacement.

After correctness passes, use `tools/load.py` for registration bursts before sale, registrations after sale, aggregate status polling, and single-request polling (`--mode poll --request-id ID`). It reports throughput, p50/p95/p99 latency and error count. Use a new event namespace for each comparable run. Capture Redis `INFO stats`, `INFO commandstats`, `INFO persistence`, `SLOWLOG GET 20`, CPU and memory before/after each run. Sample during traffic for instantaneous Redis operation rates.

For a controlled one-Pod versus multiple-Pod comparison, temporarily remove the HPA in an isolated benchmark cluster, set API replicas to 1, run identical traffic, then repeat at 2 and 5 replicas. Restore the HPA from the manifest afterward. Send traffic through a real Service ingress/load balancer: `kubectl port-forward service/...` selects one Pod and cannot measure balanced multi-Pod throughput. Repeat runs and record resource limits, worker count, dataset size and concurrency. Do not infer Kubernetes scaling from a single local container result.

Known scaling limits: batch transitions currently read the event to validate global order and batch membership, then optimistically write only changed records. `/queue` and aggregate `/status` also read the event; individual request polling reads one hash field. At very large event sizes, add bounded eligible-queue discovery and maintained aggregate counters before interpreting multi-Pod gains. AOF `always` trades write throughput for persistence.

## Verified locally (2026-10-29)

- Eleven waiting-room tests passed with Lua-enabled fakeredis; all three Redis-specific tests also passed inside Docker against real Redis 7.
- Five dispatcher recovery tests passed.
- Docker API ran on port 5001 with two Gunicorn workers/four threads each. HTTP duplicate bursts, sale opening, late arrivals and repeated starts passed.
- Full queue and request-record equality survived API and Redis restarts with AOF enabled.
- One short pre-sale burst: 300 registrations, concurrency 24, 1,895.82 requests/s, p50 11.28 ms, p95 17.42 ms, p99 23.66 ms, zero errors. This is a smoke measurement, not a scaling conclusion.
- No Kubernetes context was configured, so Pod replacement, metrics availability and multi-Pod benchmarks have not been executed. Actual downstream services were not running; callback/retry logic was tested with mocks and real Redis, not a live end-to-end payment deployment.
