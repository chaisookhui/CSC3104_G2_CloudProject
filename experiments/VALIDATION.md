# Validation records

<!-- followup-20261119:latest-results:start -->
**Latest measured follow-up:** [Results and evidence](../docs/FOLLOWUP_EVALUATION_RESULTS.md) cover 30 matched F2/F3/F6 scheduler pairs, four full HPA cycles, 21 capacity trials and nine burst trials. All bursts passed; capacity outcomes were mixed. Highest observed passing offers at 1/2/4 API replicas were 200/250/250 requests/s, with 3/3, 1/3 and 1/3 passing trials at those rates. The saved-data audit passed 1,046 checks with zero failures. The original 25-case baseline remains separate and unchanged.

No follow-up trial remains pending. The current main results report and instructions integrate follow-up findings within the relevant test cases.
<!-- followup-20261119:latest-results:end -->

This file retains historical executions. Current final results are in
`output/validation/all25/all25-audit.json`, the
[25-case results report](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf)
and [evidence index](../docs/VALIDATION_EVIDENCE.md): all 25 local cases PASS,
15 newly verified plus 10 complete v9 cases re-audited, with 321 audit checks PASS.
`output/validation/robustness-results.md` describes the earlier development runs,
not the final 25-case status. The obsolete browser workbench,
catalogue and its authoring utilities have been removed; references below describe
the earlier tested revision, not current commands.

## Earlier documentation/frontend validation

At that revision, the submission guide was `output/pdf/GROUP02_INSTRUCTIONS.pdf`,
with an editable Markdown source beside it and 18 procedures across the eleven
sections. The current guide has 25 cases. Test cases are no longer displayed in the main application;
the CLI supplies evidence capture and measurements. The earlier technical handbook
is retained as an archived document.

Executed successfully: 74 Python unit/controlled-integration checks (12 experiment
tools, 2 measurement summaries, 20 launcher, 4 reset scope, 21 allocation, 5
dispatcher recovery, 8 memory-backed waiting/checkout, 2 frontend context), plus
22 browser-recovery and 3 legacy workbench checks. The allocator/dispatcher checks
use SQLite and controlled responses; browser checks use simulated tab contexts.
Host Python 3.11 used existing pure-Python environment packages. Compilation,
CLI argument help and document structure/layout were checked separately.

Docker's Linux engine pipe was unavailable and the local Kubernetes API could not
be reached. No deployed booking/fault/scaling tests or real-store integration
suites were rerun. The Redis suite could not import the missing host `redis`
package. These environment failures are distinct from passed memory-backed tests.
Do not treat the historical results below as current-source deployment acceptance.

## Earlier integration validation

These are implementation/integration checks performed during this revision.
They are **not** a completed research article, a heavy-load capacity result,
or a statement that all 30 case cards have passed.

Environment: Windows x64, Docker Engine 29.9.3 / Compose 5.7.0, cgroup v2,
single-node Kind Kubernetes v1.36.4, PostgreSQL 17 and Redis 7. The host launcher
used Python 3.11; service tests used their container/development runtimes.
No paid cloud environment or metrics-server was installed.

## Executed checks

| Check | Recorded result | Scope |
| --- | --- | --- |
| Allocator unit/concurrency/recovery tests | 21 passed | Includes FCFS ordering, durable policy conflict and decision timestamps |
| Waiting-room tests with real Redis | 12 passed | Used temporary namespaced keys in Redis database 15; includes lab-only replay guard, saved ordering and eligibility timing |
| Experiment input/guard/metric tests | 12 passed | Deterministic F1-F7 traces, coverage crosswalk, main-target rejection, path safety, missing timing, per-row fragmentation and scoped overtakes |
| Frontend context tests | 2 passed | Actual namespace label, main rejection and no secret export |
| Frontend recovery tests | 22 checks passed | Independent tabs, same-user idempotency, stale response protection and recovery |
| Workbench tests | 3 checks passed | Missing capability labels, unavailable observations, no automatic PASS, safe imported result rendering |
| F1 balanced paired smoke | PASS, twice during development/final acceptance | Eight customers per policy; actual queue/batch/policy and identical inventory checked |
| F7 release/later-wave paired smoke | PASS | Six customers per policy; confirmation/cancel/expiry then late arrivals |
| F6 fragmented paired smoke | PASS | Eight customers per policy; alternating fixture, 120-second TTL |
| F5 80%-occupied paired smoke | PASS | Eight customers per policy; fixed initial occupied inventory |
| C01 direct contention smoke | PASS | Ten concurrent client workers, ten overlapping HTTP lifetimes; ten reserved single seats in Section C; all invariant counts zero |
| Q02 registration calibration | PASS | Five scheduled registrations/s for two seconds; not a full ramp/spike or capacity study |
| Real-network booking checker | PASS | Normal confirmation, duplicates, decline/retry, cancel, capacity, expiry and late payment rejection; new workbench assets accessible |
| W2 allocator pause/resume | PASS | Saved QUEUED work observed before resuming; original request/hold completed |
| W1 payment worker stopped | PASS | Payment API HTTP 200 while pending work persisted; original hold/deadline recovered after worker returned |
| R3 seat-API outage | PASS | Saved payment remained pending during dependency outage, then confirmed same hold without deadline change |
| R2 storage pod replacement | PASS | Same holds/payments/queue and PVC UIDs survived; a new booking confirmed after restoration |

The bounded integration runs used only the initially absent disposable
`csc3104-check` namespace and removed it afterwards. They did not reset the main
deployment or the existing lab. The existing lab was subsequently reset only
after the user's explicit permission, to prepare clean manual experiments.

## Evidence

- `.local/test-results/research-smoke-20261110-191244/verification.json`
- `.local/test-results/research-smoke-20261110-191244-F1/` (also F5, F6, F7)
- `.local/test-results/research-smoke-20261110-191244-contention/`
- `.local/test-results/research-smoke-20261110-191244-register/`
- `.local/test-results/acceptance-20261110-193648/`
- `.local/test-results/acceptance-20261110-193648-pair/`

The final paired run used the same working-source fingerprint in both before/after
captures and both policy executions. Raw snapshots include real pod image IDs,
configuration, replica readiness, trace identity, fixed-batch jobs, database
timestamps and all offered customer outcomes. Safe shareable copies are in
`output/validation/`; inspect `FCFS_pair_smoke.json` directly as historical JSON.
Those small samples are examples of execution evidence, not statistical findings.

## Not demonstrated by these runs

- Statistical fairness across ten or more independent saved seeds, or all seven
  scenario distributions under production-scale load.
- 50/100/500-client contention, sustained high arrival rates, a calibrated large
  k6 test, or per-pod ingress/load distribution.
- The complete 1/2/3/4/8-worker and 1/2/4-API scaling matrices with resource metrics.
- RF1-RF6 exact distributed commit/reply-loss, stale-lease and poison-work injection;
  unit recovery tests support the design but are not those Kubernetes experiments.
- Metrics/HPA or paid-provider cost experiments. No resource provider was present;
  missing CPU/memory observations are explicitly unavailable.
- Public customer/admin authorization. The demo user picker is not trusted login.
- CI execution of this unpushed working tree or full deployment on Docker 24/28.
  The configured CI matrix must run before claiming those remote results.

The revised handbook and frontend mark these boundaries rather than inventing
measurements or representing a completed checklist as a pass.
