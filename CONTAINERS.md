# Allocation and seat-store containers

Run all commands below from the repository root in PowerShell. These Linux images
package the existing code without changing the allocation policy or seat logic.
Each service has one image, reused by its API, worker and initialization job.

## Local database and configuration

Cloud deployment is on hold. `compose.core.yaml` runs PostgreSQL 17 together with
seat-store and allocation. Both APIs and workers connect to `postgres:5432` over
the Compose network. Migration jobs wait for PostgreSQL to become healthy, and
APIs/workers wait for their migrations to finish.

Generate local credentials (no host Python installation is required):

```powershell
.\deploy\core\configure.ps1
```

This creates ignored `src/seat-store/.env` with random passwords, or preserves an
existing file. It uses the same credentials as the database-only Windows setup.
For a new setup with an occupied port, pass `-DatabasePort 5433`. For an existing
file, change `POSTGRES_PORT` and its two host database URLs together. Containers
always use port 5432 internally. Generated passwords are URL-safe; encode special
characters in the password when manually constructing connection URLs.

The persistent volume remains `csc3104-seat-store_postgres_data`, preserving the
original Docker database. Bootstrap creates the non-superuser `seat_store` role,
`seat_booking` and the separate `seat_booking_test` database on an empty volume.
Seat-store and allocation use separate tables in `seat_booking` for this local
setup. Existing volumes retain their original credentials; changing `.env` does
not change their passwords. Native PostgreSQL data is separate and is not copied
into Docker by these commands.

If the old database-only project is running, stop it once before switching:

```powershell
docker compose -p csc3104-seat-store --env-file src/seat-store/.env -f src/seat-store/compose.yaml stop postgres
```

The restored database-only Compose file and core stack now share the
`csc3104-core` project and database service. Use the core file to manage the full
stack. Never run two PostgreSQL processes against the same data volume.

The core stack reads `src/seat-store/.env`; the previous database URL settings in
`deploy/core/.env` are no longer used. Optional callback overrides may be supplied
with a second `--env-file deploy/core/.env` after `--env-file src/seat-store/.env`.
Set `CORE_WAITLIST_URL` to a payment URL reachable from containers, for example
`http://host.docker.internal:5004` (the host-only `.env` value is not used by core).
For a complete container setup, this guide covers the core database, seat-store
and allocation. Waiting-room, dispatcher, frontend and payment retain their
existing Compose files. Payment containers can reach this database through
`host.docker.internal` at `POSTGRES_PORT`; configure their URL and run their
payment migrations as described in the payment README. Dispatcher retains its
persistent SQLite default for the local single-host demo.

Stop any host allocation API on 5002 and host seat-store API on 5003 before starting
their container replacements. Also stop their host worker processes to keep the
demo's worker count predictable. The core stack manages PostgreSQL too. A host dispatcher can
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

Or build and start the complete core setup including PostgreSQL:

```powershell
docker compose --env-file src/seat-store/.env -f compose.core.yaml config --quiet
docker compose --env-file src/seat-store/.env -f compose.core.yaml up -d --build
docker compose --env-file src/seat-store/.env -f compose.core.yaml ps -a
Invoke-RestMethod http://127.0.0.1:5003/health
Invoke-RestMethod http://127.0.0.1:5002/ready
```

`seat-init` runs `python manage.py init-db` (migrations and non-destructive seed).
`allocation-init` runs `python app.py init-db`. Both should exit with code 0;
they are one-shot jobs. APIs and workers wait for their initialization job to
succeed. Existing seat maps must match `SEAT_MAP_TIER`; initialization fails rather
than replacing an incompatible map. These commands preserve existing bookings/jobs.

PostgreSQL runs alongside these four application services:

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
docker compose --env-file src/seat-store/.env -f compose.core.yaml up -d --scale allocation-worker=4
docker compose --env-file src/seat-store/.env -f compose.core.yaml logs --tail 100 allocation-worker seat-worker
```

Use a batch spanning A-D to observe concurrency. One party per section remains the
policy, so a batch containing only Section A will still allocate sequentially.
API replicas are not configured for Compose scaling here because their fixed host
ports would collide; put a gateway/load balancer in front before scaling those.

To stop the core containers while preserving PostgreSQL data in the named volume:

```powershell
docker compose --env-file src/seat-store/.env -f compose.core.yaml down
```

Do not add `--volumes` / `-v` to `down`: that deletes the database volume.

The database test suites still need a separate `*_test` PostgreSQL database and
`TEST_DATABASE_URL`; do not point automated database tests at development bookings.
See the service READMEs for their existing test commands. A successful build or
health check alone does not prove booking, restart recovery or load behavior.
