# Complete project in Docker

Run all commands from the repository root. Start Docker Desktop in Linux-container
mode. Python is needed only for the launcher; it uses standard libraries.

## One main startup command

```powershell
python demo.py
```

This launches **one Compose project, csc3104-core**, using `compose.core.yaml`:
frontend, five APIs, five background workers, PostgreSQL and Redis. The three
initialization/migration containers should exit successfully; that is normal.
Open **http://127.0.0.1:18080**. Only the frontend is published on host loopback;
backend services communicate through internal Docker DNS and container ports.
The existing service-specific Compose files remain available for independent
module development, but are not needed for the full project.

On first launch, `demo.py` creates ignored `.env.core` with random database
credentials and an internal payment token. It preserves the file and all data on
later launches. `core.env.example` documents the available settings; editing an
initialized database's passwords in the file alone does not rotate its stored
credentials. Keep `.env.core` private and retain it with your development volumes.
The application password must be URL-safe because Compose inserts it into DSNs.
The generated hexadecimal values meet that requirement.

The frontend defaults to port 18080 to avoid other local projects. Override a port
or batch size for one invocation with `python demo.py --port 18082 --batch-size 10`.
Edit `.env.core` for persistent settings. Holds default to 300 seconds.

Equivalent direct Compose command (after `.env.core` exists):

```powershell
docker compose --env-file .env.core -f compose.core.yaml up -d --build --wait
```

The full stack now provisions its OWN PostgreSQL/Redis volumes. It does not reuse
`src/seat-store/.env`, the legacy database volume, or the old external-core URLs.
The PostgreSQL initialization script runs only for a new volume and creates four
service-owned databases with non-superuser roles. This local setup shares one
application password across those roles; deployment-specific credentials and
least-privilege migration/runtime grants remain cloud hardening work.
Allocator and dispatcher both use PostgreSQL, not SQLite. Waiting room uses Redis,
not in-memory state. No API/worker container contains durable booking data.

The standalone PostgreSQL setup in `src/seat-store/compose.yaml` and
`deploy/core/configure.ps1` remains available for module development. Its
`csc3104-seat-store_postgres_data` volume is not overwritten or automatically
migrated into the main stack. Do not invoke the main Compose file with only
`src/seat-store/.env`: the full stack uses `.env.core` and its service-owned
databases. This keeps the current main project's existing data and credentials
consistent after integrating the standalone PostgreSQL changes.
Module-only database commands use the separate legacy project identity so they
cannot replace the main stack's PostgreSQL container with another volume.

## Check or stop the project

```powershell
docker compose --env-file .env.core -f compose.core.yaml ps -a
docker compose --env-file .env.core -f compose.core.yaml logs --tail 100
python demo.py --stop
```

Stopping preserves the PostgreSQL and Redis volumes and all bookings. Restarting
also preserves confirmed seats and queue state: it is not a fresh-sale reset.
Do not delete volumes to fix credentials or unresolved jobs. The launcher never
resets seats, removes dispatcher state, or stops another Compose project.

API health/readiness does not establish worker progress. Payment's shared worker
heartbeat/backlog can be inspected with:

```powershell
docker compose --env-file .env.core -f compose.core.yaml exec -T payment-worker python service.py monitor
```

## Repeat the full-network acceptance check

The checker creates real mock bookings, including confirmed seats, and requires an
empty pre-sale queue. Use a dedicated disposable project, not existing bookings.
It sends all booking operations through the frontend proxy over real HTTP and
lets the actual workers process them. In PowerShell:

```powershell
$env:FRONTEND_PORT = '18081'
$env:HOLD_TTL_SECONDS = '30'
try {
    docker compose -p csc3104-booking-check --env-file .env.core -f compose.core.yaml up -d --build --wait
    if ($LASTEXITCODE -ne 0) { throw 'Test stack failed to start' }
    python tests/docker_booking_smoke.py --base-url http://127.0.0.1:18081 --allow-bookings
    if ($LASTEXITCODE -ne 0) { throw 'Booking acceptance failed' }
} finally {
    docker compose -p csc3104-booking-check --env-file .env.core -f compose.core.yaml down --volumes
    Remove-Item Env:FRONTEND_PORT
    Remove-Item Env:HOLD_TTL_SECONDS
}
```

`down --volumes` in this example intentionally deletes ONLY the named disposable
test project's data. Use that project name only for tests. The main project's data
is separate. The 30-second holds accelerate expiry testing; normal holds remain
five minutes. The check covers frontend assets, service proxying, Redis admission,
automatic batching/allocation, duplicate submissions/payments, successful payment,
decline/retry with unchanged deadline, cancellation, unavailable capacity, expiry
and rejection of late payment.

This is a local development/demo stack. The frontend still exposes trusted admin
and internal payment operations through its proxy; keep it on loopback. Customer
identity/authorization, authoritative UI refresh on every terminal outcome,
Kubernetes deployment, injected network/Pod failures and load/fairness/cost
measurements remain separate acceptance work. Persistent volumes alone do not
provide database high availability or backups.
