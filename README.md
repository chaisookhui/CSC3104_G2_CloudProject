# CSC3104 Group 2: Fair Seat Allocation

We are building a ticketing system that allocates adjacent seats to whole parties
of 1-4 people. We will compare the proposed Demand-Cycle policy with correct
baselines using measured results. Its fairness benefits are hypotheses to test.

## What currently works?

| Component | Current purpose |
| --- | --- |
| Root `app.py`, port 5000 | Small Flask application with `/health`. It checks that Flask runs, not the database or the full booking system. |
| `src/seat-store/`, port 5003 | Existing seat/hold service: PostgreSQL transactions, adjacent holds, confirmation, expiry and retryable expiry callbacks. It has database integration and concurrency tests. |
| Other `src/` folders | Preserved placeholders. The allocator, waiting room and waitlist/payment implementations on other branches have not been integrated here. |

This is not yet an end-to-end booking system. Seat-store's current schema represents
one inventory, without `sale_id`. Durable intake/allocation progress, complete
payment/waitlist integration and final service contracts remain owner-led work.

## Windows installation

Install Python **3.14.3 (64-bit)**. Choose one PostgreSQL backend: Docker Desktop
with Linux containers, or installed native PostgreSQL 17+ server tools. Both use
the same schema, application role and migrations. Open PowerShell in your repository
folder. For Docker, start Docker Desktop, wait for its engine, then run:

```powershell
python --version
.\setup.ps1
```

If Docker/WSL is unavailable, install PostgreSQL 17+ and add its `bin` directory
to PATH (so `initdb` and `pg_ctl` work). Then use:

```powershell
.\setup.ps1 -NativePostgres -DatabasePort 5433
```

This creates an isolated PostgreSQL cluster in the ignored `.local/postgres`
directory, bound to `127.0.0.1:5433`. It does not require the administrator password
of another PostgreSQL installation and does not change that installation. Keep
`.local/postgres` and the generated `.env` to preserve this project's data and
credentials. Do not run both backends against the same `.env`.

Setup checks the Python version, installs the pinned runtime and test dependencies
into the root `.venv`, and checks dependency compatibility. It then uses the
selected backend to start PostgreSQL, create separate
`seat_booking` and `seat_booking_test` databases, apply migrations and seed the
development seats (A/B/C = 30/20/10). The application role is not a superuser.
Local passwords are generated into the ignored `src/seat-store/.env` file.
Existing configuration, data volumes and bookings are preserved.

To install just Python/Flask and run the foundation test without a database:

```powershell
.\setup.ps1 -PythonOnly
.\test.ps1 -SmokeOnly
```

If Python is elsewhere, pass `-Python 'C:\path\to\python.exe'`. For a first setup
with an occupied database port, choose another `-DatabasePort`. If PowerShell blocks
scripts, use a process-local policy, for example:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

No environment activation or global execution-policy change is needed. Existing
module-local `.venv` directories are unused by these scripts; leave any existing
environments intact until their owners choose to remove them.

## Start Flask and PostgreSQL

For the small foundation app:

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

For the database-backed seat-store, in another window:

```powershell
.\src\seat-store\run.ps1
```

That script reads `POSTGRES_BACKEND` from local configuration, ensures PostgreSQL
is running, applies pending migrations and starts
the seat-store API with its existing expiry and callback threads. In another
PowerShell window, check both applications:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health
Invoke-RestMethod http://127.0.0.1:5003/health
```

The first returns `status=ok`; the second also returns `service=seat-store` and
`storage=postgresql`. These are local development servers. They are not production
deployment commands. No waitlist service is integrated yet, so expiry callbacks
remain pending and retry; seat release still works.

Stop an application with Ctrl+C. PostgreSQL stays running and retains its data.
For Docker, stop only this project's database without deleting it:

```powershell
docker compose -f .\src\seat-store\compose.yaml stop postgres
```

For the isolated native backend:

```powershell
.\.venv\Scripts\python.exe .\src\seat-store\native_db.py stop
```

Restart either backend with `.\src\seat-store\run.ps1`.

See [the seat-store README](src/seat-store/README.md) for its API, booking examples,
configuration and native-PostgreSQL alternative. Internal mutation endpoints are
for trusted local development; caller authentication is not implemented here.

## Run tests

After full setup, run both suites from the repository root:

```powershell
.\test.ps1
```

The root smoke test runs first, followed by the existing seat-store suite in a
separate Python process. This keeps the two current `app.py` modules separate.
Run seat-store alone with `.\src\seat-store\test.ps1`.

Database tests require the separate database configured by `TEST_DATABASE_URL`,
with a name ending in `_test`. Each test creates and drops its own schema there;
development bookings are not reset. Missing PostgreSQL is an error for this suite,
not a reason to substitute mock storage. The root smoke test needs no PostgreSQL.

GitHub Actions runs the Windows foundation setup/test and Linux real-PostgreSQL
seat-store tests on pull requests and pushes to `main` or `twy`. Its credentials
are disposable test values. Adding the workflow locally does not prove a hosted
run passed; check the Actions result after the change is pushed.

## Shared development conventions

- Use Python 3.14.3, root `.venv`, and `pip`. Runtime dependencies and their
  transitive versions are pinned in `requirements.txt`; Pytest and its dependencies
  are in `requirements-dev.txt`. Module requirements delegate to these lists.
- Add dependencies only when actual code needs them. Update the relevant pins,
  install with `python -m pip install -r requirements-dev.txt` using the environment's
  Python, run `pip check`, and rerun the affected tests. Do not freeze an unrelated
  global environment into this repository.
- Preserve the current service directories and imports for now. Coordinate module
  moves and shared contracts with consumers before changing them. There is no
  approved shared-package migration in this setup change.
- Seat-store owns seat/hold writes. Other components must not independently update
  those tables. Allocation decides which request gets a turn; seat-store currently
  selects and commits the adjacent block. Cross-service recovery still needs an
  agreed protocol; a remote call is not one shared database transaction.
- Keep secrets in ignored local configuration. `.env.example` contains dummy
  values. `.venv`, `__pycache__` and test caches are generated locally, not source.
- Work on a contributor branch. Before opening a PR, fetch and compare against the
  latest `main`, coordinate conflicts, run the relevant tests and inspect the diff
  for unrelated files or credentials. Describe changes and actual test results.
  Ask for teammate review and merge after checks pass; do not push directly to
  `main`. Branch protection must be configured separately in GitHub.

## Troubleshooting

- **Docker cannot connect:** start Docker Desktop in Linux-container mode and wait
  until `docker info` succeeds. Docker's WSL backend requires WSL; use the native
  setup above if it is unavailable. `-PythonOnly` still supports basic Flask setup.
- **Wrong Python:** `.python-version` records the supported version; it does not
  install it. Setup refuses a mismatched existing environment rather than deleting it.
- **Database login fails:** preserve the generated `.env`. Changing its passwords
  does not change an initialized PostgreSQL volume. Do not delete the volume to
  repair credentials; coordinate recovery with the database owner.
- **Port already used:** change `POSTGRES_PORT` and both database URLs together in
  an existing `.env`; `-DatabasePort` only configures a newly generated file.
  `-NativePostgres` also selects a backend only when generating a new `.env`;
  changing an existing backend requires an explicit data/configuration review.
- **Health differs between ports:** port 5000 checks only Flask; port 5003 checks
  PostgreSQL access and initialized sections. One succeeding does not prove the other.
