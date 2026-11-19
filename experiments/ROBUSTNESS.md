# Extended robustness experiments

<!-- followup-20261119:latest-results:start -->
**Latest measured follow-up - 19 November 2026:** [Results and evidence](../docs/FOLLOWUP_EVALUATION_RESULTS.md) cover 30 matched F2/F3/F6 scheduler pairs, four full HPA cycles, 21 capacity trials and nine burst trials. All bursts passed; capacity outcomes were mixed. Highest observed passing offers at 1/2/4 API replicas were 200/250/250 requests/s, with 3/3, 1/3 and 1/3 passing trials at those rates. The saved-data audit passed 1,046 checks with zero failures. The original 25-case baseline remains separate and unchanged.

No follow-up trial remains pending. The current main results report and instructions include dated follow-up supplements.
<!-- followup-20261119:latest-results:end -->

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

## Browser access and returning users

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

## Clean lab preparation

Build/load images with `python demo.py --kubernetes` after source changes.
Before **each independent scenario below**, reset only the lab:

```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

This deletes previous lab bookings/PVCs, not main data or saved evidence. Restart
any manual lab port-forward and sign in again after resetting. Workload commands
make their own temporary forward and verify the actual namespace.

## 1. Thousands of users, traffic spike and queue correctness

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

## 2. Mixed-size concurrent allocation

```powershell
python experiments/run.py contention --count 40 --workers 32 --mixed --run mixed-r1
```

Sizes 1/2/3/4 compete for the fresh ten-seat C fixture. Check party sizes,
adjacency, distinct ownership and SQL invariants. The exact winning mixture is
scheduler dependent. A no-fit HTTP 200 is not a reservation. Existing single-seat
mode remains available without `--mixed`.

## 3. Fairness objective and paired policy analysis

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

## 4. Payment/cancellation and expiry races

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

## 5. Abrupt crash, lost reply and sustained dependency failure

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

## 6. Waiting-room API scaling

```powershell
python experiments/run.py scale-api --reset-lab --rate 50 --duration 30 --repeats 3 --run api-scale-r1
```

This resets only lab before each 1/2/4-replica trial, alternates trial order and
keeps offered traffic/seed constant. Compare achieved throughput, P95/errors,
generator saturation and `served_by_instance`. The service response header
identifies which waiting-room pod handled a call. More replicas need not improve
throughput if Redis, the gateway or generator is the bottleneck. Allocation-worker
1/2/4 comparisons remain the existing `compare --replicas` experiments.

## 7. Optional local HPA

Use [the full scaling studies](SCALING_STUDIES.md) for automated, separate API
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

## Evidence and interpretation

Source tests prove specific logic; deployed experiments prove their recorded
workload only. Preserve raw arrivals/customers, before/after captures, summary,
invariants and interrupted records. Never relabel an inconclusive run as PASS.
Use `output/validation/all25/all25-audit.json` for the final selected case evidence
and `output/validation/tc-fixes/FINAL_REPORT.md` for full performance/fault detail.
`output/validation/robustness-implementation.json` records the earlier 12 November
revision, including its incomplete HPA attempt; it remains historical. No cost,
real-payment, full account-system, storage
HA, consensus, cloud-node autoscaling or universal fairness claim is added.
