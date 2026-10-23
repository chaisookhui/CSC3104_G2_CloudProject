# Mock payment and checkout service

This service owns mock payment attempts, checkout projections, cancellation intents,
recovery jobs and incoming/outgoing event delivery. Seat-store remains the only
seat/hold writer. Admission owns queue positions, close/rejoin and preference changes.
No real charge, refund, external payment provider or financial settlement exists.

## Implemented behaviour

- Existing POST /payments and GET /payments/{id} wire shapes remain supported.
- `success`, `decline`, `timeout` remain mock payment outcomes. `decline` means a
  rejected payment attempt, NOT a user rejecting their seats. Retrying a declined
  attempt uses a new attempt_key and never extends the original hold deadline.
- Attempt history is separate from booking state. A declined attempt remains
  `attempt_status=declined` when another attempt confirms the booking. Legacy
  `status` remains a booking projection (`failed` means an active declined attempt).
- New payment attempts require an active, unelapsed hold; database time checks the
  deadline precondition. Seat-store still decides confirmation atomically after its
  locks. A read/precheck is never a cross-service reservation guarantee.
- One pending attempt per hold is database-enforced. Identical persisted retries
  can be read during seat-store outage; changed input under the same key conflicts.
- Explicit user rejection uses POST /checkouts/cancel. The cancellation intent is
  durable BEFORE any remote mutation. Payment never writes seat-store tables.
- Cancellation, confirmation and expiry are reconciled by exact hold ID. If
  confirmation wins, cancellation reports confirmed; it never releases paid seats.
- Incoming events are durably deduplicated before acknowledgement and validated
  against authoritative historical hold state before processing.
- Atomic PostgreSQL work claims, leases, fenced acknowledgements, delayed retries,
  visible BLOCKED work and operator retry support independent recovery processes.
  Long-lived pending checkout/payment work does not consume the failure budget.
- Terminal checkout projection and its notification are committed together. Event
  IDs stay stable through retries. Notification delivery is at least once; receivers
  must deduplicate event IDs. No exactly-once network guarantee is claimed.

## Current integration boundaries

**Seat-store cancellation has NOT been implemented in this change.** Leave
SEAT_CANCEL_PATH empty until its owner supplies an idempotent endpoint accepting
`{request_id, hold_id}` and returning the existing hold-result shape with
`hold_status=CANCELLED` (or the authoritative terminal state that won the race).
A pending cancellation against an active hold becomes visibly BLOCKED when the
endpoint is unconfigured or unsupported. No cancellation success or seat release is
fabricated. After seat-store is upgraded, configure the path and retry the SAME
blocked work/action; do not create a new offer or payment window.

Payment does not implement admission's close/rejoin endpoint, assign positions,
automatically enrol users in a waitlist, or call the legacy policy selector.
`policy.py` is retained, marked legacy, for owner coordination. A user explicitly
rejoining needs admission to create one new entry at the back with a new request ID.
An unavailable allocation can rejoin without any checkout, so admission also owns
that path. Later checkout cancellation must not rewrite completed batch outcomes.

SEAT_STORE_URL retains port 5003 for compatibility. Dispatcher also defaults to
5003 elsewhere in the repository. Resolve that collision with the owners, then
configure URLs together; this payment change does not edit their services.

The allocator's confirmed-result null-expiry validation issue, section D inventory,
request/attempt lookup after a lost hold response, durable admission/dispatcher
recovery and frontend checkout discovery remain with their respective owners.

## Independent local configuration

Use the root Python 3.15.0 environment and pinned dependencies. Copy .env.example
to an ignored .env in THIS directory, or export environment variables. Runtime no
longer imports seat-store configuration or reads its .env. PAYMENT_DATABASE_URL is
preferred; exported DATABASE_URL is accepted as a compatibility fallback. Existing
local database credentials may be supplied explicitly; never commit them.

Required:
- PAYMENT_DATABASE_URL: PostgreSQL DB with payment table permissions.
- SEAT_STORE_URL: reachable API base (default http://127.0.0.1:5003).

Optional:
- SEAT_CANCEL_PATH: empty until the exact-hold cancellation endpoint is ready.
- PAYMENT_STATUS_URL: terminal checkout event receiver; empty retains unsent events.
- PAYMENT_HOST / PAYMENT_PORT: 127.0.0.1 / 5004 locally; bind 0.0.0.0 in a container.
- PAYMENT_HTTP_TIMEOUT / PAYMENT_WORKER_INTERVAL: 5 seconds / 1 second.
- PAYMENT_API_TOKEN: optional internal Bearer credential on all business endpoints.
  Existing seat-store expiry sender does not attach this credential. Coordinate its
  caller before enabling. This token does not establish user ownership; an exposed
  frontend/gateway must authenticate users and authorize their request/hold IDs.

From the repository root, in separate terminals:

```powershell
.\src\waitlist-payment\run.ps1 -Command init-db
.\src\waitlist-payment\run.ps1 -Command serve
.\src\waitlist-payment\run.ps1 -Command worker
```

Portable equivalents are `python src/waitlist-payment/service.py init-db`, `serve`
and `worker`. Initialisation is explicit; serving does not silently alter schemas.
Multiple workers must share the SAME PostgreSQL database. HTTP calls occur outside
payment DB transactions. Leases do not prevent duplicate remote calls after slow
requests/crashes; exact-hold idempotency and monotone projections preserve effects.

## APIs and states

| Method | Path | Input / meaning |
|---|---|---|
| POST | /payments | {request_id, hold_id, outcome, attempt_key}; existing {payment_id,status} result |
| GET | /payments/{payment_id} | Existing {status} booking projection |
| GET | /payments/{payment_id}/details | Attempt identity, immutable outcome, attempt_status and legacy status |
| POST | /checkouts/cancel | {request_id, hold_id, action_key}; 202 pending or 200 already terminal |
| GET | /cancellations/{action_id} | Action result and recovery state/error |
| GET | /checkouts/{hold_id}?request_id=... | Refresh exact hold; seats, booking reference, deadline, attempts and permitted actions |
| GET | /checkouts/{hold_id}?request_id=...&cached=true | Last known projection during outage, explicitly labelled cached |
| POST | /notify/expired | Existing expiry event, exact legacy retries supported |
| POST | /notify/holds | Version 1 hold.expired / hold.cancelled / hold.confirmed events |
| GET | /health | Process liveness; no DB/dependency probe |
| GET | /ready | Payment schema/storage readiness and work counts; not proof of worker liveness |

Errors are JSON: 400 invalid input, 401 missing internal credential when enabled,
404 missing resource/hold ownership, 409 conflicting action/key or closed checkout,
413 oversized body, 503 unavailable/malformed dependency or storage, 500 unexpected
internal failure. Public callers must not directly control mock outcomes in a real
payment product. These are prototype internal APIs.

Attempt states: pending -> succeeded | declined | closed. `closed` means the hold
finished without this attempt being reported as successful (e.g. expiry/cancellation
or another authoritative confirmation). The immutable outcome remains separate.
Legacy payment status: pending / failed / confirmed / expired / cancelled.
Booking states: active -> confirmed | expired | cancelled. A stable booking reference
is the confirmed hold ID; a redundant tickets table is unnecessary for this mock.
Cancellation states: pending -> cancelled | expired | confirmed. A pending action
with BLOCKED recovery means intervention/integration is needed, NOT cancellation.

A refreshed checkout is a point-in-time observation, not permission to bypass the
next authoritative mutation. Cached state can be stale. GET by historical hold ID
returns that hold's history; it is not a claim about current ownership of reused
seat IDs. APIs require a known hold ID; admission/allocator must supply the original
request-to-hold handoff and recover it after disconnect.

## Events, retries and recovery

Legacy expiry fields {event_id,request_id,hold_id} remain accepted, with optional
section/seats/expired_at from current seat-store. General events add version=1 and
type=hold.expired, hold.cancelled or hold.confirmed. UUIDs, bounded identifiers,
optional unique seat IDs and timezone-aware timestamps are validated. Same event ID
with changed payload returns 409. Receipt acknowledges persistence, not completed
reconciliation; unresolved/mismatched events are visible as work.

Terminal notifications POST to PAYMENT_STATUS_URL with Idempotency-Key=event_id:

```json
{"version":1,"type":"checkout.cancelled","event_id":"stable-UUID",
 "request_id":"original-request","hold_id":"exact-UUID","hold_status":"CANCELLED"}
```

The receiver must acknowledge with HTTP 2xx only after durable acceptance. Blank URL
leaves events pending. These notifications are a proposed integration contract;
no consumer endpoint has been invented or enabled in teammates' services.

Transient failures back off up to 300 seconds and become BLOCKED after 10 failures.
Unsupported cancellation and permanently invalid events block visibly immediately.
Pending authoritative results are rechecked after 5 seconds; unconfigured outgoing
notifications after 30 seconds. Independent jobs continue. Inspect and retry:

```powershell
.\src\waitlist-payment\run.ps1 -Command work-status
.\src\waitlist-payment\run.ps1 -Command retry-work -WorkId 'cancel:ACTION-UUID'
```

Retry only after resolving the recorded dependency/problem. Only BLOCKED work can
be reset; intent IDs and remote idempotency identity never change. Worker handles
SIGINT/SIGTERM and finishes its current bounded call before exiting. A crash leaves
an abandoned lease reclaimable after 30 seconds. Work timestamps/errors/counts aid
monitoring; API /ready alone cannot establish worker progress. Watch oldest pending
work/last updates and blocked counts externally.

## Migration and permissions

`init-db` records checksummed payment-owned migrations in wy_schema_migrations.
It adopts the existing schema.sql baseline, adds attempt history/checkouts/actions/
recovery/outbox tables, and backfills pending work without deleting legacy records.
Existing failed/declined history is preserved. Applied migration text must not be
edited; add another migration for later changes. No seat-store table is altered.

Run migrations once using an owner role, then grant a payment runtime role SELECT,
INSERT, UPDATE on the wy_* runtime tables (and SELECT on wy_schema_migrations).
It needs no seat/hold write privileges and no superuser/CREATE DATABASE permission.
Database role provisioning belongs to the database owner; do not silently change
teammates' shared role. Migration/backup access is separate from routine serving.

Before upgrading an existing shared database, take a database-owner-approved backup.
Test restoration into a separate database, run init-db there, then inspect pending
work and checkout history. Roll back application/schema together; an older release
cannot understand CANCELLED or the new action tables. Never drop the shared volume
or delete unresolved work to force progress. The service assumes a single sale's
inventory; multi-sale IDs require coordinated changes outside this service.

## Packaging and deployment

Build from the repository root:

```text
docker build -f src/waitlist-payment/Dockerfile -t ticketing-payment:local .
```

The image copies explicit runtime files, not .env, tests or teammates' code. API and
worker use the same image with different commands. The development Flask server is
used for this bounded prototype; it is not a measured production serving setup.

Payment-only Compose uses an EXTERNAL database and seat-store:

```text
docker compose -f src/waitlist-payment/compose.yaml --profile migration run --rm migrate
docker compose -f src/waitlist-payment/compose.yaml up -d api worker
```

Supply variables from the invoking environment or the explicit payment env file.
Container localhost is not the host or another Pod. Use reachable addresses such as
host.docker.internal for host-based local services, or service DNS in Kubernetes.

For deploy/payment.yaml, build/load the image, create ConfigMap payment-config with
SEAT_STORE_URL and PAYMENT_HOST=0.0.0.0 (and optional cancellation/status URL keys),
and Secret payment-secrets with PAYMENT_DATABASE_URL (and optional PAYMENT_API_TOKEN).
Run `python service.py init-db` once in a migration Job using those same references
before starting workloads. The manifest contains only payment API/worker/service;
database storage/HA, seat-store and admission are outside this change. Worker replicas
are configurable and do not each get private storage. No actual cluster deployment,
image build or scaling performance is implied by these files.

## Tests and CI handoff

```powershell
.\src\waitlist-payment\test.ps1
# Existing compatibility/regression tests (separate process):
.\src\seat-store\test.ps1
```

New tests require PAYMENT_TEST_DATABASE_URL (or TEST_DATABASE_URL) naming a dedicated
*_test database. Test-only fixtures may read the existing seat-store local .env for
that test DSN; runtime does not. Each test creates/drops an isolated schema. They
use real PostgreSQL persistence and controlled remote holds, plus live HTTP response
loss and independent worker-process claim tests. Fake cancellation responses model
the future endpoint; they are NOT proof that current seat-store can cancel.

The existing root CI already exercises seat-store/WY regression tests. Add a separate
CI command `python -m pytest src/waitlist-payment/tests -q` with its PostgreSQL test DSN
to include the new suite. This change deliberately leaves teammates' root workflow
and test runner untouched. Run suites separately to avoid existing generic app/db
module import collisions.

Remaining end-to-end acceptance: real seat-store cancellation and event contract,
admission identity/close/rejoin/status receiver, allocator hold handoff/recovery,
full-network failure tests, container/cluster startup, and measured load/recovery.
The pure legacy waitlist policy is not evidence those flows are implemented.
