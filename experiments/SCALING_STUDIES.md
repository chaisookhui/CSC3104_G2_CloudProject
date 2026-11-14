# Reproducible TC-19, TC-23 and TC-24 studies

Run one deployed experiment at a time from the repository root. These commands
erase only `csc3104-lab`; export any lab evidence first. The dedicated Kind
kubeconfig is used; the global kubectl context is not used or changed.

## Build and deploy

```powershell
python -m pip install -r experiments/requirements-load.txt
python demo.py --kubernetes --check
```

For a new cluster, use `python demo.py --kubernetes`. To update an existing
cluster without redeploying the main application, build and load its images:

```powershell
docker compose --env-file .env.core -f compose.core.yaml build
python -c "import sys; sys.path.insert(0,'infra/k8s'); import local; local.load_images(local.kind_binary())"
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

The study commands also reset/deploy the lab before every independent trial.
Use new run IDs, including when repeating an interrupted command.
The new dispatcher uses `/queue/next/<batch-size>`. When updating without a lab
reset, deploy the new waiting-room API before the dispatcher. The full `/queue`
endpoint remains available. Derived Redis indexes rebuild from canonical records
after older writers; no existing customer history is discarded.
Dispatcher progress now stores active work separately from append-only history
and receipts in the same database. Existing inline data migrates transactionally.
Upgrade both dispatcher processes together; old binaries cannot hydrate the new
history tables. A downgrade requires exporting/recombining those records first.
For an upgrade that retains existing state, quiesce both dispatcher-api and
dispatcher-worker and wait for their old pods to exit before starting either new
version. Keep Redis/PostgreSQL volumes, finish the waiting-room API upgrade first,
then start both new dispatcher processes. A mixed old/new dispatcher rolling
upgrade is unsupported. These experiments use fresh lab storage instead.
The study reset path uses fresh lab storage; the main namespace is not migrated.
PostgreSQL allocation workers use committed batch notifications as wake-up hints
and retain durable polling for missed hints/outages. SQLite keeps its polling
path. No extra message broker is required.
The final common Kind budget uses a one-core gateway limit and two-core
PostgreSQL limit, following observed gateway saturation and database throttling.
API/worker limits and all memory limits are unchanged. Use the same manifests
throughout a replica comparison; do not combine measurements from older budgets.

## Exact workloads and acceptance

```powershell
python experiments/study.py --case 19 --reset-lab --run TC19-verified
python experiments/study.py --case 23 --reset-lab --run TC23-fixed
python experiments/study.py --case capacity --reset-lab --run TC23-capacity
```

TC-19 repeats the original schedule three times: 5/s for 10 seconds, 100/s for
20 seconds, and 5/s for 10 seconds, exactly 2,100 unique offers. It retains the
one-second launch-lag limit and the existing 600-second admission deadline. It
checks acknowledged IDs, reconciles ambiguous replies, validates stable unique
positions 1..N and complete allocation outcomes, and runs PostgreSQL invariants.
`UNAVAILABLE` is valid inventory exhaustion. A separate fresh-lab mixed test uses
40 parties, sizes 1-4, 32 client workers and Section C's ten seats.

TC-23 fixed load is 50/s for 30 seconds (1,500 requests), 1/2/4 API replicas,
three repetitions each, alternating replica order. Each trial resets the lab,
verifies exact ready replicas, confirms Redis and all four PostgreSQL databases,
and checks actual responding pod IDs. HPAs are removed before manual scaling.
The capacity grid adds 20/40/60/80/100 requests/s for 30 seconds at each replica
count. This exploratory grid has one trial per point; repeat it for confidence.
Its thresholds are declared before execution: complete accepted/reconciled load,
zero HTTP errors, maximum launch lag <=1 second, P95 <=1,000 ms, accepted
throughput >=95% of offered rate, all requested replicas serving, no missing or
duplicate IDs, and zero SQL violations. A fixed-load PASS alone establishes
comparable correct trials, not a throughput speedup.

The host async generator uses a persistent aiohttp session and a 4,096-connection
capacity, sufficient for 200 arrivals/s with a 15-second request timeout without
an implicit worker queue. It never retries submissions. Launch time is the
aiohttp headers-send callback after connection acquisition; this is a client
launch measurement, not server receipt or a packet-capture timestamp. Connection
acquisition is included in launch lag. A failed send remains a transport failure. Generator drops, launch lag,
rejections, timeouts, ambiguous outcomes and accepted/reconciled registrations
are recorded separately. The full original schedules remain unchanged.
Client configuration/session preparation precedes the offered-arrival clock and
is recorded separately, including header/session preparation and its CPU time.
No HTTP connection or registration is warmed up. Every offered request retains
its original offset, count and rate; connection acquisition and any stall after
arrivals begin still count toward the original one-second launch-lag limit.

## HPA experiments

Install Metrics Server only if it is absent; an existing working installation
does not need replacing:

```powershell
python experiments/run.py autoscale --install-metrics --run metrics-config
python experiments/run.py autoscale --disable --run metrics-config-cleanup
python experiments/study.py --case 24-api --reset-lab --run TC24-api
python experiments/study.py --case 24-worker --reset-lab --run TC24-worker
```

Each target is evaluated separately. The test starts with one ready replica and
attaches only that target's HPA, with 1..4 replicas, a 50% CPU target, immediate
scale-up recommendations, a 60-second downscale stabilization window and bounded
policies (one additional pod per 30 seconds; one removal per 60 seconds).
No manual replica changes occur after HPA attachment.
For the worker-only cycle, the waiting-room API dependency is fixed at four ready
replicas before measurement. The worker alone starts at one and autoscaling alone
changes its replica count. The earlier one-API combined-load failure is preserved;
this isolation is explicit in configuration snapshots and the summary.

Phases: 120-second low baseline (API 2/s; worker 1/s); the original 180-second
spike (5/s for 45 seconds, 100/s for 90 seconds, 5/s for 45 seconds; 9,450 offers);
600 seconds with zero new arrivals; the identical 9,450-offer repeat spike;
30 seconds of final observation. Additional baseline/repeat traffic does not
replace any of the original load. API registrations remain pre-sale. The worker
test genuinely opens the sale so allocation jobs exist; no CPU burner is used.

The API retains its 50m CPU request. The lab worker request is experimentally
200m (500m limit unchanged): measured idle workers consumed roughly 21-25m each,
so a 100m target at one pod accommodates four idle workers' aggregate overhead.
The original 30m target could keep multiple idle workers alive indefinitely.
This is a starting calibration, not a guaranteed worker scaling result. If CPU
does not track real allocation demand, the result stays inconclusive. Backlog
autoscaling may then be appropriate, but no new scaling stack is installed.

PASS requires the ready-replica sequence 1 -> more than 1 -> 1 -> more than 1,
in phase order, actual CPU above target during high load and below target at the
end of recovery, complete load delivery, and zero SQL violations. Worker recovery
also requires a measured drained backlog. Missing evidence remains inconclusive.
Removing an HPA during cleanup never counts as automatic scale-in.

The worker retains an explicit ten-minute checkpoint. If that checkpoint is
missed, its original-window status stays INCONCLUSIVE. An additional diagnostic
window can observe up to 2,400 more seconds for actual waiting-room and SQL work
to drain, followed by 300 seconds of idle observation and the unchanged repeat
spike. This later functional cycle is reported separately; it cannot replace a
missed ten-minute criterion. No arrival count or rate is lowered.

## Evidence and graphs

Each run is under `.local/test-results/<run-id>/`. It contains raw JSON/CSV
arrivals, original payloads and identities, response headers/latencies, admission
records, preflight, configuration/source hashes, CPU/memory/HPA/pod samples,
backlog, events and pod logs (including previous containers after restarts).
`timeline.jsonl` is flushed incrementally. Interrupted runs retain their errors
and partial arrivals. Kubernetes metrics may be sampled from a longer cached
window; they are not per-request instantaneous CPU measurements.

```powershell
python experiments/study_report.py .local/test-results/TC19-verified .local/test-results/TC23-fixed .local/test-results/TC23-capacity .local/test-results/TC24-api .local/test-results/TC24-worker
```

The report writer creates CSV, Markdown tables and PNG/SVG graphs from saved
measurements only. Preserve failing and incomplete trials alongside passing ones.
The generator runs outside Kind on the host, but Docker and the host still share
physical hardware. Record the captured CPU/RAM limits and avoid other benchmarks
at the same time. More API replicas may be limited by the gateway, Redis, CPU
limits or shared storage; do not infer a capacity improvement from replica count.

Restore the ordinary lab after exporting evidence:

```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

## Regression checks

After the performance studies, run the existing SQL integration suites using a
Python environment with the project's test dependencies (`requirements-dev.txt`,
the waiting-room dev requirements and `psycopg-pool`):

```powershell
python experiments/postgres_checks.py --reset-lab --run SQL-regression
python experiments/regression.py --reset-lab --full-coverage --run deployed-regression
```

The first command creates a dedicated `tc_regression_test` database inside the
lab's PostgreSQL instance, then runs the unchanged seat, payment and five-service
integration suites separately. Credentials are passed through the child process
environment and are not printed. The second uses existing baseline, registration,
policy-replay, race, committed-reply/crash and 60-second outage assertions at the
original workloads. TC14,TC15 and each TC20 variant run three fresh repetitions.
TC16 runs three repetitions at each1/2/4worker count with
both policies; TC18 runs all ten independent F1seeds42–51 with both policies.
Each policy resets to matching inventory, and its logs are saved before the next
reset. The optional `--bounded` mode limits repetitions and seed coverage for a
diagnostic; it cannot recertify the original repeated/ten-seed studies.
These checks run after load studies to avoid resource contention. Resetting the
lab afterward removes their dedicated test database.

## Interrupted setup

A failed Kubernetes setup command never establishes a passing workload result.
If a replica/capacity cohort stopped before creating the next trial directory,
resume the same planned cohort with:

```powershell
python experiments/study.py --case 23 --reset-lab --run TC23-fixed --resume
```

Resume keeps completed trials, including inconclusive/failed ones, verifies their
rate/duration/replica/repetition conditions, and requires unchanged application
image IDs. It never overwrites an incomplete workload directory. Such a workload
must remain preserved in its original cohort; use a new run ID for a new study.
Original interruption records are retained even when subsequent unstarted trials
complete. New preflight/timeline records include Windows physical/commit memory;
less than 256 MiB available commit blocks launch rather than reducing the load.

If all HPA phases and the full raw timeline completed but result analysis failed,
the recorded experiment can be assessed without generating traffic or changing
replicas, while its original lab data is still present:

```powershell
python experiments/study.py --case 24-api --run TC24-api --finalize-recorded
```

This mode requires the reporting interruption and no existing final summary. It
checks the original schedules, complete delivery, observation durations, actual
CPU/ready transitions, current SQL invariants and every accepted registration ID.
It cannot overwrite a completed failed/inconclusive result. Missing/null CPU
samples remain missing rather than becoming zero utilization.

Implementation references: [aiohttp sessions and connection pools](https://docs.aiohttp.org/en/stable/client_advanced.html),
[Waitress concurrency options](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html),
[Requests session pooling and cookies](https://requests.readthedocs.io/en/latest/user/advanced/#session-objects),
and [Kubernetes HPA behavior](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/).
