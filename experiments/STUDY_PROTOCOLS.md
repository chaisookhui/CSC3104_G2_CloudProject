# Study protocols

Use this guide for exact experimental procedures. For lab setup and functional/
browser verification, start with [README.md](README.md). For recorded execution
history, see [VALIDATION.md](VALIDATION.md); current findings are indexed in
[the evidence index](../docs/VALIDATION_EVIDENCE.md).

Run commands from the repository root, one deployed experiment at a time. Preserve
existing lab evidence before resetting and use a fresh run ID for each new attempt.
The commands below retain their original workload sizes, deadlines and checks.
Completed evidence is not automatically a PASS or a production-capacity guarantee.

- [Robustness and failure recovery](#robustness)
- [Burst, replica capacity and autoscaling](#scaling)
- [Additional paired and boundary studies](#follow-up)

<a id="robustness"></a>

## Robustness and failure recovery

The final recorded results are in the [25-case report](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf)
and [evidence index](../docs/VALIDATION_EVIDENCE.md): all 25 local cases PASS,
15 newly verified plus 10 full-scope final v9 cases re-audited. The 321 audit
checks passed. The procedures below do not imply that every optional extension
or production claim was tested.

These procedures address the eight evaluation areas and the professor's first
four questions. Cost analysis is excluded. Test cases stay in the CLI and guide.
Run from the repository root. Keep all `.local/test-results` evidence before a
lab reset. Each command needs a unique `--run` value. Never overlap experiments.

| Evaluation area | Added evidence |
|---|---|
| Waiting room and queue | Thousands of offered arrivals; acknowledged-ID and position reconciliation through admission |
| Allocation/concurrency | Mixed sizes, adjacency, whole parties, ownership and SQL invariants |
| Demand-Cycle fairness | Independent paired seeds, explicit objective, gaps/Jain index, waits/overtakes/utilization |
| Payment/cancellation/expiry | Concurrent calls at active and near-expiry holds; consistent terminal winner |
| Fault tolerance | Committed reply loss, runtime-level worker kill, storage outages and durable recovery |
| Distributed scalability | Separate allocation-worker and waiting-room API replica experiments |
| Frontend/session recovery | Saved browser-owned users, disconnect/reload/reopen, terminal-state recovery |
| Cloud operations/security | Optional observed HPA, customer ownership, CSRF and administrator separation |

### Browser access and returning users

The container stack enables signed browser ownership when its generated
`PAYMENT_API_TOKEN` is present. Customers can create up to 12 browser-owned demo
identities, view their own queue entries and act on their own holds. The gateway
checks ownership on reads, registration, payment and cancellation. Arbitrary
seat mutations, queue administration and other users' bookings require an
administrator or a separate operator bearer token. CSRF checks cover writes.
The CLI reads the local namespace's operator credential without sending it to
browser code. Do not expose internal services outside the private network.

For the professor's Overview, Batches, Seat map and simulation controls, retrieve
the password locally and use **Administrator sign in** in the page header:

```powershell
python experiments/access.py --namespace csc3104-lab
```

Use `--namespace csc3104` for main. Resets regenerate credentials. Compose uses
`python experiments/access.py --compose` to derive its password from `.env.core`; optionally set
`FRONTEND_ADMIN_PASSWORD` in the frontend environment. Native development with
no token remains an explicitly unauthenticated demo. Never publish that mode.
For HTTPS deployment set `FRONTEND_COOKIE_SECURE=true`; local HTTP stays loopback.

This is possession of a signed browser cookie, not verified personal identity
or a cross-device account. Cookies last seven days; deleting cookies, changing
the signing credential or using a different browser loses access. Closing tabs
alone preserves ownership. Administrator sessions grant access to all demo users.

To test recovery: create a customer in a separate browser profile, register,
record the user/request/hold IDs, queue number and deadline, then disconnect,
reload and close/reopen the browser. Return using the saved-user picker. Expect
the same booking, no repeated registration or extended deadline, and an honest
expired outcome after a long absence. Repeat with two tabs and during payment.
A different profile must receive HTTP 403 for that customer's request and for
sale opening, direct seat mutations and payment/cancellation with copied IDs.
Sign out of administrator access before checking customer restrictions.
Bookings created before the ownership upgrade remain available to administrators.
Old client storage alone cannot grant ownership of an earlier arbitrary user ID.

### Clean lab preparation

Build/load images with `python demo.py --kubernetes` after source changes.
Before **each independent scenario below**, reset only the lab:

```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

This deletes previous lab bookings/PVCs, not main data or saved evidence. Restart
any manual lab port-forward and sign in again after resetting. Workload commands
make their own temporary forward and verify the actual namespace.

### 1. Thousands of users, traffic spike and queue correctness

```powershell
python experiments/run.py register --rate 100 --duration 40 --profile spike --admit --timeout 600 --run surge-r1
```

About 2,100 offers: 5/s baseline, 100/s middle surge, 5/s recovery. Arrival JSON/CSV
retain scheduled/actual launch times, response latency, rejection, unknown replies
and generator drops. `admission.json` verifies acknowledged IDs, positions 1..N,
stable positions through admission and final database invariants. P95 is recorded
separately for baseline/surge. No unacknowledged result is silently counted as a
success. PASS requires every offered arrival accepted/reconciled, no missing IDs,
complete admission and safe storage. Inconclusive means capacity was not proved.
The local generator, frontend and port-forward can limit achieved load.

### 2. Mixed-size concurrent allocation

```powershell
python experiments/run.py contention --count 40 --workers 32 --mixed --run mixed-r1
```

Sizes 1/2/3/4 compete for the fresh ten-seat C fixture. Check party sizes,
adjacency, distinct ownership and SQL invariants. The exact winning mixture is
scheduler dependent. A no-fit HTTP 200 is not a reservation. Existing single-seat
mode remains available without `--mixed`.

### 3. Fairness objective and paired policy analysis

```powershell
python experiments/run.py trace --scenario F1 --count 80 --seed 42 --output .local/traces/fairness.json
python experiments/run.py compare --trace .local/traces/fairness.json --reset-lab --hold-ttl 120 --seeds 10 --replicas 1 --run fairness-10-seeds
```

The comparator resets lab before each policy and uses identical input and
inventory within each pair. Consecutive independent seeds differ between pairs.
`--repeats` repeats the same seed; it does not increase independent sample size.
This longer suite can take substantial time. Start with one seed as a smoke test.

Objective: equal opportunity for party sizes 1..4 **within the same section**.
Each summary reports the maximum-minus-minimum reservation-rate gap and Jain's
index `(sum(rates)^2)/(n*sum(rate^2))`. Smaller gaps and indices nearer one indicate
more equal rates. All-zero service has no score. Unknown outcomes or missing size
groups prevent an interpretable full-size conclusion. Use waits, overtakes,
sample sizes and utilization alongside rate equality. Adjacency and capacity can
make equal outcomes infeasible. Comparison reports paired descriptive differences,
not a statistically significant or universal superiority claim.

### 4. Payment/cancellation and expiry races

```powershell
python experiments/run.py race --run lifecycle-r1
```

Reset again with `--hold-ttl 20`, then run:

```powershell
python experiments/run.py race --near-expiry --run lifecycle-expiry-r1
```

A barrier releases payment and cancellation calls together, optionally just before
the original expiry. Confirmed, cancelled or expired can be a valid winner.
HTTP 409 is a valid competing-operation rejection. Check the authoritative final
checkout plus zero partial-party, ownership and duplicate-payment violations.
Repeat trials because actual thread/network scheduling controls the winner.

### 5. Abrupt crash, lost reply and sustained dependency failure

After a fresh reset before each command, run separately:

```powershell
python experiments/run.py fault --scenario lost-reply --run reply-r1
python experiments/run.py fault --scenario worker-crash --run crash-r1
python experiments/run.py fault --scenario redis --seconds 60 --run redis-r1
python experiments/run.py fault --scenario postgres --seconds 60 --run sql-r1
python experiments/run.py fault --scenario both --seconds 60 --run dependencies-r1
```

The lab-only proxy forwards a seat hold to the real seat service and drops the
committed reply. Crash mode exposes that commit checkpoint, then SIGKILLs the
allocator process before acknowledgement. Recovery must reuse the same request,
hold and original deadline; no second hold is created. Worker restart evidence,
checkpoint data and authoritative hold history are saved. If the original hold
expired, reconciliation returns its terminal outcome and lets the batch finish.

Outage mode first saves a confirmed booking and an unfinished allocation job,
then scales the selected storage StatefulSet(s) to zero for 5..180 seconds.
It records failed/available reads, then restores original replicas in `finally`.
The confirmed hold and queued job must survive; the queued customer eventually
allocates without a new identity. Transient allocator failures retain durable work
with capped backoff; permanent conflicts still become BLOCKED. This is recovery
after interruption, not highly available storage or a node-failure result.

### 6. Waiting-room API scaling

```powershell
python experiments/run.py scale-api --reset-lab --rate 50 --duration 30 --repeats 3 --run api-scale-r1
```

This resets only lab before each 1/2/4-replica trial, alternates trial order and
keeps offered traffic/seed constant. Compare achieved throughput, P95/errors,
generator saturation and `served_by_instance`. The service response header
identifies which waiting-room pod handled a call. More replicas need not improve
throughput if Redis, the gateway or generator is the bottleneck. Allocation-worker
1/2/4 comparisons remain the existing `compare --replicas` experiments.

### 7. Optional local HPA

Use [the full scaling studies](STUDY_PROTOCOLS.md#scaling) for automated, separate API
and worker baseline/spike/600-second recovery/repeat-spike evidence. Install the
registration client with `python -m pip install -r experiments/requirements-load.txt`.
The following commands configure HPAs and generate the original traffic; they
are not a complete autoscaling acceptance test by themselves.

```powershell
python experiments/run.py autoscale --install-metrics --run hpa-config-r1
python experiments/run.py register --rate 100 --duration 180 --profile spike --run hpa-load-r1
```

Use a fresh lab before enabling HPAs. In another window record timestamped
`python infra/k8s/kubectl.py -n csc3104-lab get hpa,pods` and `top pods` during
load and for 600 seconds after load. `capture` also saves HPA state.
Require actual scale-out and subsequent scale-in with healthy customer state
before claiming automatic scaling; configured HPA or Ready pods alone do not
prove it. The 1..4-replica CPU HPAs target waiting-room and allocation workers.
Low worker CPU may not trigger a scale-out for an I/O-bound workload.
The original spike remains 100/s for 180 seconds with the spike profile (9,450
offers). Drops or excessive launch lag keep that trial inconclusive; preserve it
and fix the generator/environment rather than lowering this workload to claim
PASS. Any separate calibration must be labeled as a different workload.
Stabilization windows and unfinished allocation demand can delay scale-in.

The pinned metrics-server v0.8.1 installation is restricted to the private
`kind-csc3104` context and uses a local self-signed kubelet TLS exception. It is
not a production TLS setting. Normal deployment does not install metrics-server.
See [Kubernetes HPA documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/)
and [metrics-server releases](https://github.com/kubernetes-sigs/metrics-server/releases/tag/v0.8.1).

```powershell
python experiments/run.py autoscale --disable --run hpa-disable-r1
```

Disable HPAs before manual scaling comparisons. Removing them leaves the current
replica count; reset lab or scale explicitly to restore the baseline.

### Evidence and interpretation

Source tests prove specific logic; deployed experiments prove their recorded
workload only. Preserve raw arrivals/customers, before/after captures, summary,
invariants and interrupted records. Never relabel an inconclusive run as PASS.
Use `output/validation/all25/all25-audit.json` for the final selected case evidence
and `output/validation/tc-fixes/FINAL_REPORT.md` for full performance/fault detail.
`output/validation/robustness-implementation.json` records the earlier development
revision, including its incomplete HPA attempt; it remains historical. No cost,
real-payment, full account-system, storage
HA, consensus, cloud-node autoscaling or universal fairness claim is added.

<a id="scaling"></a>

## Burst, replica capacity and autoscaling

Additional F2/F3/F6 scheduler comparisons, repeated full HPA cycles and explicitly
opted-in higher-rate trials are documented in [STUDY_PROTOCOLS.md#follow-up](STUDY_PROTOCOLS.md#follow-up).
They retain the original defaults and original evidence as separate baselines.

The full final v9 studies below passed their recorded local acceptance conditions;
their unchanged raw evidence is part of the final 25-case ledger. See the
[current evidence index](../docs/VALIDATION_EVIDENCE.md) and results report.
They remain measured local workloads, not universal capacity or production claims.

Run one deployed experiment at a time from the repository root. These commands
erase only `csc3104-lab`; export any lab evidence first. The dedicated Kind
kubeconfig is used; the global kubectl context is not used or changed.

### Build and deploy

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
Use a fresh run ID for a new study. Preserve raw evidence and distinguish each new independent study from the recorded results.
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

### Exact workloads and acceptance

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

### HPA experiments

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

### Evidence and graphs

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

### Regression checks

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

### Interrupted setup

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

<a id="follow-up"></a>

## Additional paired and boundary studies

The follow-up is complete; see [final observed results](../docs/FOLLOWUP_EVALUATION_RESULTS.md). Do not repeat completed studies.

This procedure adds evidence to the original 25-case ledger. It does not replace
or recertify those original results. All deployed commands use the project's
dedicated Kind kubeconfig and only `csc3104-lab`. Run one experiment at a time.
Current cohort commands and outcomes live in
`output/validation/followup-20261119/`; raw runs use the same prefix under
`.local/test-results/`. An attempt is a measurement only after it actually runs.

### Preserve before resetting

```powershell
python experiments/preserve_lab.py --run followup-YYYYMMDD-preserve-a
```

This read-only export seals original run files and submission documents into a
verified ZIP, records hashes, captures existing lab observations/logs/inventory,
and exports the lab's four SQL databases and Redis records. Its snapshot is local
private evidence. It excludes Kubernetes Secrets and kubeconfig. Do not publish
the private original archive wholesale. A failed export does not authorize a reset.

### Execute the complete sequential cohort

```powershell
python experiments/followup.py --prefix followup-YYYYMMDD --preserved followup-YYYYMMDD-preserve-a --plan-only
python experiments/followup.py --prefix followup-YYYYMMDD --preserved followup-YYYYMMDD-preserve-a
```

The plan uses the existing public `run.py trace`, `run.py compare`, and `study.py`
commands. The orchestrator records commands, logs, interruptions and run IDs.
Completed identical attempts and incomplete evidence are retained. The follow-up cohort is complete; refer to its recorded results rather than rerunning it as a new experiment.

`--skip-hpa` omits HPA when initially planning a cohort. The recorded follow-up is now complete. The recorded measurements and raw evidence are retained separately from future studies. Never adopt an incomplete
policy replay as a completed matched pair.

* TC-18: F2, F3, F6; 40 parties; seeds 42–51; batch size 10; one allocation
  worker; 120-second hold TTL; one replay per policy per seed; alternating policy
  order. Each replay records the saved trace, physical inventory and actual batch
  boundaries. F6 fixture bookings are excluded from customer outcomes.
* TC-24: two complete API cycles, then two complete worker cycles. The unchanged
  runner retains 120s baseline, 180s/9,450-offer spike, 600s with no new arrivals,
  identical second spike and 30s observation. HPA alone controls the target once
  attached. Worker tests hold the waiting-room API at four Ready replicas. The
  original ten-minute checkpoint and any later diagnostic result stay separate.
* TC-23: a 200/250/300 requests/s grid for 30s at 1/2/4 fixed API replicas with
  HPA off. After the grid, two additional independent fresh-state trials run at
  each configuration's initially highest passing tested rate and first valid
  tested miss, where either exists. There is no extrapolation beyond 300/s.
* TC-19: three independent bursts per peak (100/150/200 requests/s), each with
  10s at 5/s, 20s peak, 10s at 5/s: 2,100/3,100/4,100 planned offers. The admission
  deadline stays 600s, with stable unique positions, IDs, terminal allocation
  outcomes and existing SQL invariant checks.

Individual capacity and burst commands are also supported:

```powershell
python experiments/study.py --case capacity --reset-lab --rates 200 250 300 --allow-high-rate-lab --repeats 1 --run fresh-capacity-a
python experiments/study.py --case capacity --reset-lab --rates 300 --allow-high-rate-lab --replicas 2 --repeats 2 --run fresh-boundary-a
python experiments/study.py --case 19 --reset-lab --peaks 100 150 200 --repeats 3 --run fresh-bursts-a
```

The higher-rate opt-in is required above 200/s and capped at 300/s. The existing
20,000 rate×duration bound, 300s duration maximum, defaults, 4,096-task pool,
15s request timeout and acceptance thresholds are unchanged. The original
`study.py --case 19` also retains its separate mixed-contention trial; the explicit
follow-up peak grid extends the burst study only.

Before traffic starts, `schedule.json` records the exact planned offsets/count.
Afterward, generator CPU time, peak outstanding tasks, spare task capacity,
drops, launch lag and response latency establish whether the scheduled traffic
was delivered. The 4,096-task pool cannot accommodate 300/s for a full 15s timeout;
observed headroom and delivery must be checked rather than assuming sufficiency.
An invalid generator attempt cannot establish a server capacity limit.

### Article tables and slide figures

Use a Python runtime with matplotlib for reporting; no cluster connection or
workload generation occurs:

```powershell
python experiments/followup_report.py --prefix followup-YYYYMMDD
python experiments/audit_followup.py --prefix followup-YYYYMMDD
python experiments/export_followup.py --prefix followup-YYYYMMDD
```

The report directory contains `RESULTS.md`, a compact `ARTICLE_EVALUATION.md`,
CSV/JSON measurements, pending rerun commands, a paired scheduler PNG/SVG,
per-cycle HPA PNG/SVG timelines and offered-versus-achieved traffic PNG/SVG.
The read-only raw auditor checks count/latency consistency, saved identities,
trace/inventory/batch matches, fixture exclusions, source/image continuity and
support for claimed HPA passes. A correctly recorded failed or inconclusive
experiment remains available; an audit pass does not turn it into a workload pass.
The new exported ZIP is separately named and verified; original sealed archives
remain unchanged. Known local credentials are redacted in exported copies only.

Fairness comparisons use within-seed Demand-Cycle minus FCFS differences.
Unrepresented sizes remain missing. Jain is undefined without all four sizes,
known outcomes and positive service. Full-coverage rate gaps can include zero
service, so their interpretable pair counts can differ from Jain's. Scenario
fairness means average per-seed means across eligible sections; section-specific
and stratum-specific pair counts and offered denominators are also exported.
No statistical significance or fairness superiority is assumed.

HPA recovery times are first observed Ready/backlog samples relative to the
first spike's nominal offer-end; the original runner's 600-second recovery-window
outcome is reported separately. CPU is the Metrics Server windowed resource
measurement. These are observations of CPU-based HPA in local Kind, not cloud or
production scalability claims.

<!-- followup-20261119:documentation-link:start -->
### Current submission documents

The main results report and instructions integrate the follow-up within the relevant test cases. See the [submission checklist](../docs/FINAL_SUBMISSION_VERIFICATION.md). Article tables and PNG/SVG figures remain in the report folder.
<!-- followup-20261119:documentation-link:end -->
