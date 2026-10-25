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
