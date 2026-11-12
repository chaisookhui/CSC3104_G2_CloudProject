# Robustness validation - 12 November 2026

Branch: `twy`. Deployment: private local Kind cluster. Main confirmed-seat ownership and existing batch/hold settings were preserved. Cost analysis was excluded.

## Current deployed checks

| Check | Result | Evidence run |
|---|---|---|
| lost-reply | PASS | implementation-lost-reply-20261112-final |
| worker-crash | PASS | implementation-worker-crash-20261112-r2 |
| race-active | PASS | implementation-race-active-20261112-final |
| race-expiry | PASS | implementation-race-expiry-20261112-r2 |
| outage-redis | PASS | implementation-outage-redis-20261112-r2 |
| outage-postgres | PASS | implementation-outage-postgres-20261112-r2 |
| outage-both | PASS | implementation-outage-both-20261112-r3 |
| surge | PASS | implementation-surge-20261112-final |
| gateway | PASS | implementation-gateway-20261112-r3 |
| fairness | PASS | implementation-fairness-20261112-final |
| api-scale | PASS | implementation-api-scale-20261112-final |
| hpa-load | INCONCLUSIVE | implementation-hpa-load-20261112-final |
| autoscale | INCONCLUSIVE | See JSON capsule |
| booking-acceptance | PASS | See JSON capsule |
| browser-live | PASS | output/validation/browser-recovery.json |

The initial in-container PID 1 signal did not kill the worker; that result was corrected to INCONCLUSIVE. The runtime-level SIGKILL rerun observed a restart and recovered the same expired original hold. Outage harness retries were corrected to wait for API recovery after storage became ready. Initial attempts remain in the JSON history.

## Load and API replicas

All 2,100 offers were accepted, all admission outcomes resolved, positions remained unique and stable, and SQL invariants reported zero violations. The first smaller generator attempt dropped arrivals and was retained as inconclusive.

| Waiting-room replicas | Offers accepted | Achieved registration/s | P95 HTTP ms | Responding pods |
|---|---|---|---|---|
| 1 | 500/500 | 50.00 | 21.20 | 1 |
| 2 | 500/500 | 50.00 | 19.22 | 2 |
| 4 | 500/500 | 50.08 | 77.73 | 4 |

These are bounded fixed-rate trials, one round per replica count. They prove request participation and completeness at the offered rate, not maximum capacity or a throughput speedup. The three-round study in the instructions remains to be executed.

## Fairness

[Recorded policy comparison](fairness-comparison.md) reports two independent F1 seeds with 40 parties each, one allocation worker and matching physical inventory per pair. Rate gaps/Jain indices are conditional on section and party size; waits, overtakes and utilization are retained in the raw summaries. Two seeds are a smoke study, not the full ten-seed research protocol or a statistical superiority claim.

## Autoscaling limits

Actual waiting-room scale-out from one to four replicas was observed. The 6,300-offer load accepted 6,267 and dropped 33 in the local generator; maximum launch lag exceeded two seconds. No acknowledged IDs were lost. Scale-in was not captured in the observation window. The workload and full scale-out/scale-in cycle remain INCONCLUSIVE. Allocation-worker HPA scale-out was not asserted. Metrics-server remains available in the private Kind cluster; experimental HPAs were removed.

## Source and database regressions

Passed: 61 seat-store and 50 payment tests against disposable PostgreSQL 17 databases, nine gateway access checks, 24 allocator checks, 23 browser recovery and two browser access cases, plus the named experiment, measurement, launcher and dispatcher/checkout checks in the JSON capsule. Controlled remote responses and simulated browser contexts are separate from deployed network tests.

## Browser verification

Live Chromium verification opened the updated main interface with administrator access separated from customer controls and no test-case navigation. The password input was masked. A lab customer registered D/1, closed the tab, reopened it and selected the saved user. The original request/hold IDs, seat D-1-1, queue number 4 and displayed deadline were unchanged. Backend reconciliation found exactly one registration. See browser-recovery.json and administrator-sign-in.jpg. This is a scoped tab recovery check, not exhaustive cross-browser/offline acceptance.

## Reproduction and scope

Follow [the extended procedures](../../experiments/ROBUSTNESS.md) and the submission PDF. Raw runs are retained under `.local/test-results/` and are ignored by Git; export them separately if required for submission. The JSON capsule identifies runs, corrected attempts and limitations. No verified personal-account, storage-HA, node-failure, cloud-node-scaling, real-payment or cost claim is made.
