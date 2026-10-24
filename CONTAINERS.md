# Allocation and seat-store containers

Run all commands below from the repository root in PowerShell. These Linux images
package the existing code without changing the allocation policy or seat logic.
Each service has one image, reused by its API, worker and initialization job.

## Does PostgreSQL need to be set up first?

Building images does **not** require PostgreSQL. Running seat-store, or testing
real holds/confirmation/expiry, requires a reachable PostgreSQL server and database.
This Compose file uses external PostgreSQL; it does not install PostgreSQL or
replace your existing database volume. It initializes application tables before
starting the APIs and workers. Allocation also uses PostgreSQL here so worker
replicas share the same jobs.

If you already ran `setup.ps1`, reuse that project's database and credentials.
For the existing Docker database, start Docker Desktop in Linux-container mode,
then start PostgreSQL with its existing configuration:

```powershell
docker compose --env-file src/seat-store/.env -f src/seat-store/compose.yaml up -d postgres
```

For a first setup, use `./setup.ps1` as described in README.md. It creates the
database, role, local credentials and seat migrations. The native PostgreSQL option
also works, provided Docker Desktop containers can reach that server. A native
server listening only on loopback may need explicit listener, firewall and
`pg_hba.conf` configuration for Docker's network; keep access restricted. The
existing Docker PostgreSQL option is the simplest path for this runbook.

## Configure the containers

```powershell
Copy-Item deploy/core/.env.example deploy/core/.env
```

Edit `deploy/core/.env` with the username, password, database and port from your
existing database configuration. Do not print or commit credentials. For Docker
Desktop, change the URL host from `127.0.0.1` to `host.docker.internal`; retain the
actual published PostgreSQL port. URL-encode special characters in credentials.
The example's `replace_me` is not a working password.

For local development, both URLs can target the same `seat_booking` database:
seat-store and allocation use separate tables. The role needs permission to create
their tables. Separate service databases/roles can be supplied later without code
changes. All replicas of a service must use the same database. Do not connect this
demo to a database containing an unrelated or incompatible allocation workload.

Stop any host allocation API on 5002 and host seat-store API on 5003 before starting
their container replacements. Also stop their host worker processes to keep the
demo's worker count predictable. PostgreSQL stays running. A host dispatcher can
continue using `http://127.0.0.1:5002`. A host payment service can continue using
`SEAT_STORE_URL=http://127.0.0.1:5003`.

If a host dispatcher is running, set:

```dotenv
DISPATCHER_COMPLETION_URL=http://host.docker.internal:5005/allocator/status
```

That dispatcher must listen on an interface reachable from Docker, rather than
only loopback. Payment callbacks similarly require a reachable payment listener
(for the existing payment CLI, set `PAYMENT_HOST=0.0.0.0`). Restrict host firewall
access appropriately. Payment may remain absent for an allocation-only demo:
holds still expire, and callbacks remain in the durable outbox for retry.

## Build and start

Build only (no database connection is made):

```powershell
docker build -f src/allocation/Dockerfile -t ticketing-allocation:local .
docker build -f src/seat-store/Dockerfile -t ticketing-seat-store:local .
```

Or build and start the complete core setup once PostgreSQL is reachable:

```powershell
docker compose --env-file deploy/core/.env -f compose.core.yaml config --quiet
docker compose --env-file deploy/core/.env -f compose.core.yaml up -d --build
docker compose --env-file deploy/core/.env -f compose.core.yaml ps -a
Invoke-RestMethod http://127.0.0.1:5003/health
Invoke-RestMethod http://127.0.0.1:5002/ready
```

`seat-init` runs `python manage.py init-db` (migrations and non-destructive seed).
`allocation-init` runs `python app.py init-db`. Both should exit with code 0;
they are one-shot jobs. APIs and workers wait for their initialization job to
succeed. Existing seat maps must match `SEAT_MAP_TIER`; initialization fails rather
than replacing an incompatible map. These commands preserve existing bookings/jobs.

The four long-running services are:

| Compose service | Process | Dependency |
| --- | --- | --- |
| `seat-api` | Gunicorn on 5003 | Seat PostgreSQL tables |
| `seat-worker` | `python manage.py worker` | Same seat tables; payment callback URL |
| `allocation-api` | Gunicorn on 5002 | Allocation PostgreSQL tables |
| `allocation-worker` | `python worker.py` | Same allocation tables; `http://seat-api:5003` |

The seat worker expires holds and delivers callbacks. API containers do not start
these background tasks. The allocation worker claims jobs and calls seat-store;
it has no published port. Worker progress must be checked separately from API
health. Images run as a non-root user and exclude local configuration/data through
the root `.dockerignore`.

## Exercise the real container network

Use a development database with spare Section A seats. This creates a real hold
that will expire normally; it is not a mocked or read-only check:

```powershell
$batchId = 'container-' + [guid]::NewGuid().ToString()
$requestId = [guid]::NewGuid().ToString()
$payload = @{
    batch_id = $batchId
    requests = @(@{
        request_id = $requestId
        section = 'A'
        party_size = 1
        global_position = 1
    })
    section_demand = @{ A = @{ '1' = 1; '2' = 0; '3' = 0; '4' = 0 } }
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5002/batches -ContentType application/json -Body $payload
Invoke-RestMethod "http://127.0.0.1:5002/batches/$batchId" | ConvertTo-Json -Depth 10
```

Repeat the final GET until `complete` is true. With available seats, expect
`RESERVED` and an exact hold ID; otherwise expect `UNAVAILABLE`. A previous
unfinished batch returns 409: let it finish or reconcile it instead of deleting
durable state. Do this standalone test before starting dispatcher-driven batches,
because the allocator intentionally accepts only one active fixed batch.

To test more allocation workers:

```powershell
docker compose --env-file deploy/core/.env -f compose.core.yaml up -d --scale allocation-worker=4
docker compose --env-file deploy/core/.env -f compose.core.yaml logs --tail 100 allocation-worker seat-worker
```

Use a batch spanning A-D to observe concurrency. One party per section remains the
policy, so a batch containing only Section A will still allocate sequentially.
API replicas are not configured for Compose scaling here because their fixed host
ports would collide; put a gateway/load balancer in front before scaling those.

To stop the application containers while preserving external database contents:

```powershell
docker compose --env-file deploy/core/.env -f compose.core.yaml down
```

The database test suites still need a separate `*_test` PostgreSQL database and
`TEST_DATABASE_URL`; do not point automated database tests at development bookings.
See the service READMEs for their existing test commands. A successful build or
health check alone does not prove booking, restart recovery or load behavior.
