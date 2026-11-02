# Durable dispatcher

Local ports: waiting room 5001, allocation 5002, seat-store 5003, payment 5004,
dispatcher 5005. Environment variables override service URLs; container localhost
is not another service. See .env.example (reference only, not loaded implicitly).

From the repository root, with the root environment installed:

```powershell
.\.venv\Scripts\python.exe src/batch-dispatcher/app.py
```

This starts the API and a one-second recovery polling thread. For WSGI use the
`app:create_app()` factory from this directory and start a separate worker:

```powershell
.\.venv\Scripts\python.exe src/batch-dispatcher/app.py worker
```

At least one worker must run. `/ready` proves storage access, not worker progress.
Watch current state, attempts and last_error through `/status`. The worker polls
even when idle: late registrations do not depend on a successful
sale-start trigger or allocation callback. No recursive Flask test-client calls
are used in production.

## Containers (dispatcher only)

From the repository root, with Docker Desktop running in Linux-container mode:

```powershell
docker compose -f compose.batch-dispatcher.yaml config --quiet
docker compose -f compose.batch-dispatcher.yaml up -d --build
docker compose -f compose.batch-dispatcher.yaml ps -a
Invoke-RestMethod http://127.0.0.1:5005/ready
docker compose -f compose.batch-dispatcher.yaml logs --tail 100 dispatcher-worker
```

This builds one non-root image and runs a Gunicorn API on port 5005 plus a
separate recovery worker. Stop any host dispatcher API and worker first.
No other services are started or changed. Start the waiting room and allocator
separately. Their default addresses are `http://host.docker.internal:5001` and
`http://host.docker.internal:5002`. Host services must listen on an interface
reachable from Docker (the waiting room's direct Python startup binds to
`0.0.0.0` already). Restrict access
to these trusted development APIs. If another Compose stack publishes a backend
only on host loopback, verify Docker-to-host connectivity; its published port
alone does not prove reachability from this container.

Override `WAITING_ROOM_URL`, `ALLOCATOR_URL` and `BATCH_SIZE` through PowerShell
environment variables or a private file supplied with Compose's `--env-file`.
Other containers on separate Compose networks can reach this API through
`http://host.docker.internal:5005` only if its host port binding is reachable;
otherwise join a shared Docker network and use `http://dispatcher-api:5005`.
Set their `DISPATCHER_URL` accordingly. Allocator completion callbacks can use
that address with `/allocator/status`; polling also recovers without callbacks.

By default both processes share SQLite at `/data/dispatcher.sqlite3` in the named
`dispatcher-data` volume. This is a single Docker host setup, with fresh state
independent of the existing repository `.local/dispatcher.sqlite3`. Do not run
two independent dispatchers against the same live sale. For multiple hosts,
set the same `DISPATCHER_DATABASE_URL=postgresql://...` on every API and worker;
the database must already exist and allow dispatcher table creation. Keep
credentials in private configuration, never in the image.

`/ready` checks storage only. Check `/status`, worker logs and a real batch through
the existing booking flow to verify dependency connectivity and worker progress.

Stop while preserving state:

```powershell
docker compose -f compose.batch-dispatcher.yaml down
```

Do not add `--volumes` if you need to retain dispatcher batches and history.
To build the image without starting any processes:

```powershell
docker build -f src/batch-dispatcher/Dockerfile -t ticketing-batch-dispatcher:local .
```

State defaults to the persistent repository `.local/dispatcher.sqlite3` file.
Preserve it across local restarts. Multiple machines/Pods must use the SAME
`DISPATCHER_DATABASE_URL=postgresql://...` and provision runtime table permissions;
never give each Pod private SQLite storage. Tables are created on first startup,
so initial provisioning needs CREATE permission. A short database lease fences
competing workers; no database transaction spans an HTTP request. Crashed leases
become reclaimable after 60 seconds.

Batch UUID and exact input are committed before claiming queue entries. Recovery
repeats the same claim, submission or outcome sync after response loss. Transient
failures back off up to 30 seconds; conflicts retain the same identity and remain
visible rather than losing requests or inventing no-seat outcomes. Persistent
contract/data errors need operator repair. Progress states are CLAIMING,
SUBMITTING, WAITING_FOR_ALLOCATION, SYNCING_OUTCOMES, COMPLETED. One active fixed
batch and the existing allocation policy are preserved.

`POST /batches/next` performs one bounded recovery pass (202 accepted/in progress,
200 idle, 503 dependency failure). It also resumes an existing batch.
`POST /allocator/status` durably deduplicates completion receipts; changed payload
under the same event ID returns 409. A 200 receipt is not proof of batch completion:
the worker independently verifies allocator results and syncs outcomes. Polling
also recovers when callbacks are absent. `/batches/current`, `/batches/history`
and `/batches/allocator-input` expose persisted state.

RESERVED outcomes include exact hold ID, status, deadline and seat IDs in the
waiting-room projection. Checkout is available earlier via the waiting room's
request checkout endpoint, which can discover completed jobs in an unfinished
batch. RESERVED is an allocation outcome, never proof of payment.

Limitations: dispatcher state/history/inbox use one JSON record; this is durable
prototype storage, not a high-throughput event ledger. The waiting room still
needs Redis/PVC for restart durability (memory mode is local development only).
Existing state lost by the former in-memory dispatcher cannot be reconstructed
by this migration; reconcile any already-stranded ADMITTED entries before upgrade.
Internal endpoints remain trusted development APIs.

Tests (run each suite in its own process to avoid legacy app/db import names):

```powershell
.\.venv\Scripts\python.exe -m pytest src/batch-dispatcher/tests src/allocation/tests -q
.\.venv\Scripts\python.exe -m unittest discover -s src/services/waiting-room/tests -v
.\.venv\Scripts\python.exe -m pytest src/seat-store/tests -q
.\.venv\Scripts\python.exe -m pytest src/waitlist-payment/tests -q
.\.venv\Scripts\python.exe -m pytest tests/test_booking_integration.py -q
```

Database suites require TEST_DATABASE_URL pointing to a dedicated `_test` database;
the payment suite also accepts PAYMENT_TEST_DATABASE_URL. Integration tests use
real PostgreSQL for seats, payment, allocator and dispatcher, an in-memory admission
store, and routed Flask HTTP contracts with injected response loss. They do not
claim a deployed Kubernetes/network/load test. CI runs these commands separately.
