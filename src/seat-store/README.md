# Module 3 - Seat/Hold State Store

This Flask service is the only writer of seat ownership. Module 2 decides which
request gets a turn; this service chooses the leftmost adjacent block and commits
the entire party together. Module 4 owns payments, waitlist policy and reoffers.

## Windows quick start

Prerequisites: Python 3.11 or later, Docker Desktop using Linux containers,
and Docker Compose v2. Start Docker Desktop and wait for its engine to be ready.
Run these commands from the repository root:

```powershell
.\src\seat-store\setup.ps1
.\src\seat-store\run.ps1
```

If Python is not on PATH, pass its executable to setup:

```powershell
.\src\seat-store\setup.ps1 -Python 'C:\Python311\python.exe'
```

Setup generates random passwords in the ignored local `.env`, installs dependencies
in `.venv`, starts PostgreSQL 17 in Docker, creates a regular `seat_store` role,
creates `seat_booking` and `seat_booking_test`, applies versioned migrations and
generates the development seat map. No manual database or table creation is needed.
The application role is not a PostgreSQL superuser and cannot create databases.

If port 5432 is already occupied, use `setup.ps1 -DatabasePort 5433` on the first
setup. For an existing `.env`, update `POSTGRES_PORT` and both database URLs together.
Existing `.env` files and database volumes are preserved. Changing passwords in
`.env` does not change credentials inside an already initialized PostgreSQL volume.
Keep the generated `.env` when restarting or recreating the container.

`run.ps1` safely reapplies pending migrations, verifies the seat map, and starts
Flask on `127.0.0.1:5003`, with independent expiry and callback threads. Ctrl+C stops
the API and threads; the database remains running. To stop only this database:

```powershell
docker compose -f .\src\seat-store\compose.yaml stop postgres
```

If PowerShell blocks unsigned scripts, run each script with a process-local policy:

```powershell
powershell -ExecutionPolicy Bypass -File .\src\seat-store\setup.ps1
```

There is no global PowerShell policy change. PostgreSQL is bound only to localhost.
Docker's named volume holds the data across container/service restarts; do not
delete the volume to restart the service.

## Verify a booking

In another PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:5003/health
# Expected: status=ok, service=seat-store, storage=postgresql

$requestId = [guid]::NewGuid().ToString()
$holdBody = @{section='A'; party_size=3; request_id=$requestId} | ConvertTo-Json
$hold = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5003/seats/hold `
    -ContentType application/json -Body $holdBody
$hold | ConvertTo-Json -Depth 5
# On a fresh map: success=true; seats A-1-1, A-1-2, A-1-3, all HELD.

$confirmBody = @{request_id=$requestId; hold_id=$hold.hold_id} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5003/seats/confirm `
    -ContentType application/json -Body $confirmBody
# Expected: hold_status=CONFIRMED and all three seats CONFIRMED.

Invoke-RestMethod http://127.0.0.1:5003/seats/A
```

For a manual expiry demonstration, set `HOLD_TTL_SECONDS=5` in `.env`, restart the
service, create a different hold, and do not confirm it. After the scan runs, its
seats become AVAILABLE. Confirmed seats remain CONFIRMED. If Module 4 is absent,
the expiry callback stays pending and is retried; seats are still released.

## HTTP contract

All timestamps are ISO 8601 UTC strings. Request IDs are non-empty strings up to
128 characters, compatible with Module 1 UUIDs. Party sizes must be JSON integers
1-4; booleans and fractional numbers are rejected. Unknown fields are rejected.

| Method | Path | JSON body | Success response |
|---|---|---|---|
| GET | `/health` | none | `{status: "ok", service: "seat-store", storage: "postgresql"}` |
| GET | `/seats/{section}` | none | Array of current seat records |
| POST | `/seats/hold` | `{section, party_size, request_id, reoffer_key?}` | `{success, request_id, hold_id, hold_status, hold_expiry, seats}` |
| POST | `/seats/confirm` | `{request_id, hold_id?}` | Updated hold outcome and seat records |
| POST | `/seats/expire` | `{request_id, hold_id?}` | Updated hold outcome and released seat records |

Successful hold response, compatible with `abril`'s Module 2 seat client:

```json
{
  "success": true,
  "request_id": "request-123",
  "hold_id": "152deeb9-8270-4824-bdbb-dc85de9673c5",
  "hold_status": "ACTIVE",
  "hold_expiry": "2026-10-18T04:05:00Z",
  "seats": [
    {
      "seat_id": "A-1-1",
      "section": "A",
      "row": 1,
      "position_in_row": 1,
      "state": "HELD",
      "held_by_request_id": "request-123",
      "hold_expiry": "2026-10-18T04:05:00Z",
      "hold_id": "152deeb9-8270-4824-bdbb-dc85de9673c5"
    }
  ]
}
```

No adjacent block: HTTP 200 with exactly `{"success": false}`. No seats or hold
are partially created. A failed no-fit attempt may be retried when capacity changes.
Error responses are `{error: "code", message: "description"}`:

| Status | Meaning |
|---|---|
| 400 | Invalid JSON, missing/unknown fields or invalid values |
| 404 | Unknown section, request or hold belonging to another request |
| 409 | Conflicting request details, expired/confirmed booking, premature expiry, or missing hold ID after reoffer |
| 413 | Body exceeds 16 KiB |
| 503 | Database unavailable, lock timeout, or uninitialized schema |

A storage timeout is never returned as `success: false`. A timed-out write may
have committed; retry the **same request and attempt key** to reconcile it.
Responses use HTTP 200 for both new holds and idempotent successful retries.

## Lifecycle and retries

Seat states: `AVAILABLE -> HELD -> CONFIRMED`, or `AVAILABLE -> HELD -> AVAILABLE`
when unpaid. Hold states: `ACTIVE -> CONFIRMED` or `ACTIVE -> EXPIRED`.
EXPIRED belongs to the hold/history, not the seat. Paid bookings cannot expire.
There is no cancellation/refund operation in this module.

Every mutation takes a PostgreSQL transaction-scoped request advisory lock, then
locks the section row. This serializes changes within a section across API
threads and processes, while other sections proceed independently. Every caller
must go through this API. Hold insertion, seat ownership, history, confirmation,
release and callback enqueue are transactional. Database constraints also prevent
two live holds for one request and inconsistent seat/hold associations.

Deadlines use database wall time checked **after acquiring locks**. At or after the
deadline, confirmation is rejected and the hold is expired in a committed
transaction even if the scanner has not reached it yet. Repeated successful holds
preserve the original seats/deadline; repeated confirmation and expiry have no
additional effect. Retrying an expired attempt returns 409 instead of starting a
new payment window. Invalid operation transitions cannot revive a booking.

The response to a repeated transition describes that hold's outcome. After an
expiry its seats may since have been reallocated; use GET `/seats/{section}` for
current ownership, not a historical expiry response.

### Reoffers: contract extension for Module 4

Module 4 should keep the returned `hold_id` with each payment record and use it
on confirmation and expiry. Request-only calls are accepted for the first hold
to maintain the original contract. Once a request has more than one hold, they
return `hold_id_required` (409), protecting reoffers against stale callbacks.

To reoffer an expired request with the same section/party size, send a unique
`reoffer_key` to `/seats/hold`. Persist the key **before calling**, reuse it for
network retries, and create a new key only for a genuinely new offer. This creates
a fresh hold ID. Reoffers require the previous hold to be EXPIRED and cannot
replace an active/confirmed booking. A changed section/party size requires a new
request ID, following the project preference-change rule. The API never chooses
which request receives a reoffer or bypasses the waitlist on its own.

## Expiry callbacks and recovery

Expiry atomically releases the full party and creates one outbox event. A separate
thread POSTs to `${WAITLIST_URL}/notify/expired` with:

```json
{
  "event_id": "57cce7cf-6651-43e1-aee5-47eb1ed56769",
  "request_id": "request-123",
  "hold_id": "152deeb9-8270-4824-bdbb-dc85de9673c5",
  "section": "A",
  "seats": ["A-1-1"],
  "expired_at": "2026-10-18T04:05:01Z"
}
```

`seats` contains seat IDs. Module 4 must acknowledge with HTTP 2xx and
`{"success": true}`, deduplicate by `event_id`, and associate the event with its
`hold_id`. All fields are additive to the original `{request_id, seats}` contract.

Network calls happen outside seat transactions. Failed delivery retries with
exponential backoff (2 seconds through 300 seconds). Persisted leases prevent
normal workers from simultaneously sending the same event; abandoned leases
become available after at least 30 seconds. Delivery is **at least once**: if Module
4 accepts an event but the acknowledgement is lost, it can receive it again.
No exactly-once network guarantee is claimed. Workers must keep running for
background expiry and callback delivery to progress.

Committed holds, confirmations, expiry history and pending callbacks survive API
restarts. On restart the scanner processes overdue holds and the dispatcher
retries pending events. This does not implement recovery of Module 1 queues or
Module 2 allocation order; those remain their owners' responsibilities.

## Configuration and other environments

The scripts work from any directory. `.env` is loaded relative to this module;
environment variables take precedence for Python processes. Do not commit `.env`
or send credentials to other module owners. `.env.example` contains placeholders.

| Variable | Default / purpose |
|---|---|
| `DATABASE_URL` | Required PostgreSQL connection URL |
| `TEST_DATABASE_URL` | Separate database whose name ends in `_test` |
| `POSTGRES_ADMIN_PASSWORD` | Docker bootstrap only |
| `SEAT_STORE_DB_PASSWORD` | Docker application-role bootstrap only |
| `POSTGRES_PORT` | `5432`, local database port |
| `SEAT_MAP_TIER` | `dev` (A/B/C = 30/20/10) or `eval` (200/100/50) |
| `HOLD_TTL_SECONDS` | `300` |
| `EXPIRY_SCAN_INTERVAL` | `1` second |
| `CALLBACK_INTERVAL` | `1` second between delivery batches |
| `CALLBACK_TIMEOUT_SECONDS` | `5` seconds |
| `WAITLIST_URL` | `http://127.0.0.1:5004` |
| `HOST`, `PORT` | `127.0.0.1`, `5003` |

Seat rows are always 10 seats long. Reinitialization with a different map refuses
to resize an existing database, preserving bookings. For evaluation, create a
separate database owned by `seat_store`, set `DATABASE_URL` to it and set
`SEAT_MAP_TIER=eval`, then run `manage.py init-db`. Do not reuse evaluation data as
the development/test database or modify applied migrations.

Without Docker, provision PostgreSQL 17+ and an application-owned database,
configure `DATABASE_URL`, install `requirements.txt`, and run:

```text
python manage.py init-db
python app.py
```

For a WSGI server use `app:create_app()`, and run `python manage.py worker` as a
separate process; the Flask factory intentionally does not start threads on import.
The direct `python app.py` entry point starts the threads itself and disables the
development reloader. The built-in Flask server is for development; deployment
packaging and Kubernetes manifests remain Module 5's responsibility.

For shared integration, deploy the API on a reachable host and configure Module
2's `SEAT_STORE_URL` to that API. Only Module 3 needs PostgreSQL credentials. A
teammate's `127.0.0.1` points to their own machine, not this computer.

## Tests

After setup, from the repository root:

```powershell
.\src\seat-store\test.ps1
```

Or from this directory:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Tests require a real running PostgreSQL instance. They fail with a setup message
when it is unavailable rather than substituting an in-memory store. Each test
creates and drops a unique schema in the separate `*_test` database; development
bookings are untouched. HTTP callback tests use a local temporary HTTP server.

Coverage includes map generation, leftmost adjacency, row boundaries,
fragmentation, whole-party rollback, request deduplication, reoffer/stale-call
handling, sixteen competing requests for the last two seats, concurrent duplicate
requests, confirmation versus expiry, independent sections, a committed booking
surviving abrupt process exit, callback retry/recovery and live background threads.
Success means all tests pass, two of sixteen contenders obtain the last two seats,
no overlapping ownership occurs, and paid bookings never expire.

Whole-system integration with the actual Module 4 remains necessary once its
payment and webhook handlers are implemented. This branch does not implement
the allocator or change its shuffle/queue-order policy.
