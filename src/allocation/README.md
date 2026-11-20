# Demand-cycle scheduler and allocation workers

For Docker API/worker setup with PostgreSQL and seat-store, see the
[core container guide](../../CONTAINERS.md).

The batch dispatcher sends a **fixed batch of up to 50 requests** (its `BATCH_SIZE`
default; this API rejects more than 100), plus its party counts for each section
A to D. This module validates the counts, ranks party sizes, persists
jobs, and lets identical general-purpose workers reserve seats through SeatStore.
It does not select global admission entries or recalculate a sliding window.

## Policy used here

This implements the clarified role agreement: repeating demand cycles, sequential
allocation within each section, and shared workers across sections.

- Rank **number of parties**, descending; smaller party size wins equal counts.
- Preserve original `global_position` order within each party size.
- Dispatch one party per size per cycle: e.g. `4,2,3,1,4,2,3,1,...`.
- Skip exhausted size groups. Rank again only for the next fixed batch.
- Workers rotate between nonempty section queues (`A,B,C,D`), skipping empty ones.
  A busy section is skipped until its current party has a saved outcome. There is
  **only one active party per section**; workers are not permanently assigned.
- Every request gets its own SeatStore attempt. A no-fit party does not stop other sizes.
- Within a section, each party finishes its seat-hold attempt before the next
  party starts. Across sections, allocations run concurrently. RETRY/BLOCKED
  outcomes keep that section from advancing.
- The next batch is accepted only when every current job is RESERVED, UNAVAILABLE
  or CANCELLED. Payment completion is not part of this gate. CANCELLED is reserved
  for future admission integration; there is no cancellation endpoint here yet.

Each hold asks SeatStore to search current inventory from the earliest row for
the leftmost fitting same-row block. The cycle does not restart at row boundaries.
New batches recalculate demand, preserve occupied seats and can fill earlier gaps.
A party that cannot fit in an earlier row is placed in a later fitting row.

## Files and responsibilities

| File | Responsibility |
|---|---|
| `algorithm.py` | Validate dispatcher snapshot/counts; compute deterministic demand-cycle jobs |
| `app.py` | Accept batches and expose persisted progress; no synchronous allocation |
| `job_store.py` | Durable job queue, atomic claims, section rotation, leases, retry and acknowledgement |
| `worker.py` | Claim an eligible section's next job, call SeatStore, deliver completion events |
| `dispatcher_client.py` | Retry batch-completion HTTP notifications with a stable event ID |
| `seat_client.py` | HTTP hold adapter, response validation, hold ID/expiry preservation |
| `demo_dispatcher.py` | Sample batches with calculated counts, for the unit tests and manual local demos |
| `mock_allocator.py` | Test-only stand-in for this API (no workers or SeatStore) used to test the waiting room and dispatcher flow |
| `tests/test_allocation.py` | Policy, validation, queue concurrency/recovery, API and client tests |

An UNAVAILABLE request is returned to the dispatcher as an outcome and ends there.
This module does not add it to any waitlist.

## Dispatcher contract

`POST /batches`, content type `application/json`:

```json
{
  "batch_id": "batch-001",
  "requests": [
    {"request_id": "r1", "section": "A", "party_size": 4, "global_position": 1},
    {"request_id": "r2", "section": "A", "party_size": 2, "global_position": 2},
    {"request_id": "r3", "section": "A", "party_size": 4, "global_position": 3}
  ],
  "section_demand": {"A": {"1": 0, "2": 1, "3": 0, "4": 2}}
}
```

Counts mean requests/parties, **not seats**. Include all four size keys, with zeros;
include exactly the sections present in the snapshot. The actual requests are
required as well as counts: workers need IDs, sizes and original queue positions.

New submission: 202, with `size_order`. Identical batch ID and snapshot: 200,
without enqueueing again (request-list order is ignored). Changed payload under the
same batch ID, reused request ID or unfinished previous batch: 409. Invalid input:
400. Queue/storage failure: 503; retry identical input and batch ID.

`GET /batches/batch-001` returns each job's state, attempts, result and error, plus
`complete`. A successful result contains `hold_id`, `hold_status`, `hold_expiry`
and seat IDs. Pass the exact hold ID to payment. A no-fit result is UNAVAILABLE.
Do not infer sold/paid status from RESERVED: it records allocation-stage success;
checkout may subsequently confirm or expire that hold. Poll SeatStore/payment for
current reservation state. `completion_notification` is `not_created` while
allocation is incomplete, then `pending`, then `delivered` once acknowledged.

### Batch completion notification

The final saved allocation outcome atomically creates **one durable completion
event for the entire batch**, not one per party or size. Workers POST it to the
URL configured in `DISPATCHER_COMPLETION_URL`:

```json
{
  "event_id": "stable-UUID-for-this-batch",
  "type": "batch.allocation_completed",
  "batch_id": "batch-001",
  "total_requests": 3,
  "outcomes": {"RESERVED": 2, "UNAVAILABLE": 1, "CANCELLED": 0}
}
```

The dispatcher should persist/deduplicate `event_id` (also sent in the
`Idempotency-Key` header), then respond with HTTP 2xx. It may admit the next batch
without waiting for payment. The batch dispatcher receives it at
`POST /allocator/status` (port 5005), the value in `.env.example`.
Unset URL: the event remains pending; polling `complete` still works.

Delivery is **at least once**: network failure, non-2xx responses or a worker crash
trigger retries of the same event with bounded backoff. A lost acknowledgement may
cause duplicate HTTP delivery; dispatcher deduplication is required. Notification
failure never changes a finished allocation back to unfinished. Shared workers
atomically claim notification delivery; there is no separate notifier Pod.

`GET /health` checks the API process; `/ready` checks the initialized queue store.
These are API probes, not worker probes. The worker is a separate polling process.

## Run a local demo on your Mac

Use your existing root `.venv`, with Flask and requests installed. Local SQLite
needs no extra package. Commands below run **from the repository root**.
The `.env.example` is a reference; these processes read environment variables and
do not automatically load that file.

Terminal 1:

```bash
export ALLOCATION_DATABASE_URL=sqlite:////tmp/allocation-demo.sqlite3
.venv/bin/python -m src.allocation.app init-db
.venv/bin/python -m src.allocation.app
```

Terminal 2 (SeatStore must be running separately on port 5003):

```bash
export ALLOCATION_DATABASE_URL=sqlite:////tmp/allocation-demo.sqlite3
export SEAT_STORE_URL=http://127.0.0.1:5003
.venv/bin/python -m src.allocation.worker
```

Run the same worker command in more terminals to try three local workers, all
using the same database file. There is one claim in flight per worker process.

Terminal 3:

```bash
# Print the dummy dispatcher's JSON without sending anything:
.venv/bin/python -m src.allocation.demo_dispatcher
# Submit batch 1 (A's cycle is 4,2,3,1):
.venv/bin/python -m src.allocation.demo_dispatcher --send
curl http://127.0.0.1:5002/batches/demo-1
# After complete=true, submit batch 2 (A's cycle is 3,4,1,2):
.venv/bin/python -m src.allocation.demo_dispatcher --second --batch-id demo-2 --send
```

Later batches use remaining inventory; earlier holds still occupy seats. Reusing
the same demo IDs returns prior results. For genuinely new requests use a new
batch ID; never change IDs just to retry a timeout. If SeatStore is absent, jobs
retry and eventually become BLOCKED; absence is not simulated as no availability.

To test with no SeatStore, PostgreSQL, Redis or dispatcher running:

```bash
.venv/bin/python -m unittest discover -s src/allocation/tests -v
```

These tests use temporary SQLite files and fake hold responses; the multi-process
queue test runs three independent worker processes. They do not prove actual
SeatStore inventory locking or PostgreSQL behaviour across network partitions.

## Shared workers and race protection

For separate hosts/Pods set `ALLOCATION_DATABASE_URL` to the **same PostgreSQL
queue database** in every API/worker process. Install the root requirements
(including psycopg) and run `app init-db` once as a migration step, before serving.
Run `init-db` again when upgrading this version: it creates the completion outbox
and backfills events for previously completed batches. Existing jobs are retained.
These new `allocation_*` tables do not modify SeatStore's tables. SQLite is strictly
for local processes sharing a local file: do not give each Pod its own SQLite file
or place SQLite on a shared network volume.

This implementation uses a SQL-backed reliable queue instead of Redis, retaining
the repository's existing PostgreSQL stack. It is an equivalent coordination
backend, not an implementation of the PDF's Redis/MySQL deployment. A Redis/MySQL
migration requires agreement with the dispatcher and SeatStore owners.

1. Short queue transactions lock a shared scheduler row (SQLite uses a local write
   transaction). Claims, section cursor and attempt tokens change atomically.
2. Workers perform SeatStore HTTP calls **outside** that queue transaction.
3. SeatStore's request idempotency and transactional section/seat locks prevent
   duplicate holds and overlapping ownership. A Python thread lock would not
   protect independent Pods, so none is used for seat safety here.
4. Claims have 30-second leases. A new claim pass recovers expired leases. Normal
   HTTP connect/read timeouts are 3/5 seconds; a very slow request may outlive its
   lease. Duplicate calls reuse the same request ID and are safe only because
   SeatStore enforces idempotency.
5. Each claim gets a fresh token; an expired/replaced worker cannot acknowledge a
   newer claim. Acknowledgement follows a durable SeatStore outcome.
6. Connection failures, uncertain responses and 5xx/408/429 retry with bounded
   backoff. No-fit is only a valid HTTP 200 `success:false` response. A 4xx conflict
   or five failed attempts becomes BLOCKED, never falsely UNAVAILABLE.
7. BLOCKED/RETRY/IN_PROGRESS jobs keep the fixed batch incomplete. Other sections
   can continue; any unfinished party prevents new party claims behind it in
   that section. Lease recovery retries that same party before allowing the next.
   A stale HTTP call may still be executing after a lease expires; it always uses
   the same request ID. End-to-end safety relies on SeatStore idempotency/locking,
   not the queue lease alone.

Recovery limitation: the queue and SeatStore are separate transactions. A crash
following a committed hold but before acknowledgement is recovered by an
idempotent `/seats/hold` retry while the original hold can still be returned. If
that hold has already expired, current SeatStore returns 409. Such a job becomes
BLOCKED for reconciliation rather than opening a new payment window. A fresh
reoffer key is never invented by the worker. Malformed responses also retry with
the same request ID. Do not delete a blocked job or fabricate no-seat results to
advance the batch. Reconciliation/cancellation tooling and durable historical
request lookup need owner integration before unattended deployment.

## Integration with other modules

- Batch dispatcher: sends batches of up to 50 requests with their counts, polls
  `complete` and receives the completion event before admitting the next batch.
  It owns global queue positions and entry eligibility.
- SeatStore: serves sections **A to D** (`ALLOCATION_SECTIONS=A,B,C,D`) and holds
  the **leftmost adjacent block in the earliest fitting row**. Workers delegate
  selection atomically rather than doing unsafe GET-then-update.
- SeatStore and this queue both use PostgreSQL. This module does not change the
  inventory schema or payment behaviour. One inventory/event is assumed.
- Payment: uses the exact hold ID from a RESERVED result. Uncertain expired-hold
  reconciliation (BLOCKED jobs) still needs manual handling.
- Docker/Kubernetes: the worker runs as one container image in compose. Kubernetes
  replicas/HPA settings are still to be added.
- Before deployment, run real PostgreSQL queue tests, integrated SeatStore
  contention tests, and Pod termination/recovery tests. Local queue tests alone
  cannot establish zero double booking for the whole distributed system.

## Worker replicas

With one request per worker process and one worker per Pod, up to four sections
can allocate simultaneously using four workers. Three workers can serve four
sections by taking turns after individual parties; idle/busy sections are skipped.
Extra workers cannot advance another party in an already busy section. Replica
count and autoscaling are deployment decisions; workers do not create/delete Pods.
