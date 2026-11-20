# Follow-up evaluation

<!-- followup-20261119:document-sync:start -->
The current [submission results PDF](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf) and [testing instructions](../output/pdf/GROUP02_INSTRUCTIONS.pdf) integrate these findings within the relevant test cases. See the [submission checklist](FINAL_SUBMISSION_VERIFICATION.md) for navigation and evidence verification.
<!-- followup-20261119:document-sync:end -->

All 64 planned evaluation units are complete: four full HPA cycles, 30 matched
scheduler pairs, 21 capacity trials and nine burst trials. Completion includes
inconclusive outcomes; it does not imply every workload or SLO passed. Three
historical interrupted attempts remain retained separately and are not extra
completed samples. No planned reruns remain.

This extends the original 25-case evidence without replacing its results. Only
the existing private `kind-csc3104` cluster and `csc3104-lab` namespace were used,
one deployed experiment at a time. Application/configuration hashes and image
IDs remained unchanged. Existing images and sealed preservation archives were
reused. No commit or branch change was made; the branch remains `twy`.

## Scheduler comparisons

Each scenario has ten matched seeds (42–51), 40 parties, batch size 10, one worker
and 120-second holds. Policy order alternates; both policies use matching traces,
inventory and actual batch boundaries. Values below are Demand-Cycle minus FCFS.

| Scenario | Mean Δ confirmed parties | Mean Δ confirmed seats | Mean Δ Jain | Mean Δ rate gap | Interpretable Jain seed / section pairs |
|---|---:|---:|---:|---:|---:|
| F2 | -0.1 | +0.4 | +0.009405 | 0 | 10 / 11 |
| F3 | +0.5 | 0 | +0.028361 | +0.0375 | 8 / 13 |
| F6 | 0 | 0 | 0 | 0 | 10 / 40 |

The original F1 trade-off (more confirmed parties but lower Jain) did not recur
on these mean paired effects. F3 nevertheless has a worse rate gap despite
higher Jain, so these results do not establish general fairness superiority.
Unrepresented sizes remain missing. Jain requires sizes 1–4, known outcomes and
positive service. F6's 35 fixture-occupied seats are excluded from customer
bookings and incremental utilization. Section/size denominators, reservation
rates, decision waits and metric-specific pair counts are retained in the CSVs.

## CPU-based HPA in local Kind

All four retained fresh cycles passed the original 120s baseline, 180s/9,450-offer
spike, 600s zero-arrival recovery, identical repeat spike and 30s observation.
Each observed actual Ready sequence 1,2,3,4,3,2,1,2,3,4. Worker tests held the API
at four Ready replicas throughout; no manual target scaling followed HPA attachment.

| Target / cycle | First scale-out after spike start (s) | One Ready after first spike offer-end (s) | Worker backlog drain after offer-end (s) |
|---|---:|---:|---:|
| API 1 | 67.7 | 150.4 | — |
| API 2 | 79.4 | 153.6 | — |
| Worker 1 | 49.7 | 574.6 | 370.3 |
| Worker 2 | 49.5 | 561.0 | 362.6 |

All original 600s recovery windows were met; no later diagnostic window replaced
an original outcome. These are observed CPU-based HPA results in local Kind.

## API capacity

The unchanged composite SLO requires P95 ≤1,000ms, achieved rate ≥95% of offered,
zero HTTP failures, complete delivery within 1s launch lag, correct IDs/SQL and
all requested API replicas serving. HPA was off; each trial offered a constant
rate for 30s and began from fresh equivalent lab state.

| API replicas | Highest observed passing rate | Passing / valid trials at that rate | First observed valid-delivery miss | Misses / valid trials at that rate |
|---:|---:|---:|---:|---:|
| 1 | 200/s | 3 / 3 | 250/s | 2 / 2 |
| 2 | 250/s | 1 / 3 | 200/s | 1 / 3 |
| 4 | 250/s | 1 / 3 | 250/s | 2 / 3 |

These are observed passing rates, not stable capacity estimates. Repeated
outcomes are mixed and non-monotonic. Three independent attempts were collected
at each selected boundary; the 250/s one-replica point has only two valid-delivery
results because one attempt exceeded the launch-lag limit.

Two complete attempts have invalid delivery: 300/s with one replica saturated
the unchanged 4,096-task pool and dropped 374 offers; an extra 250/s one-replica
trial launched all 7,500 requests but reached 4.08s launch lag. Its maximum task
dispatch lag was 4.07s, with no pool drops and peak occupancy 3,117/4,096. The
evidence identifies a dispatch delay but does not isolate its underlying cause.
Both attempts are retained and excluded from capacity-boundary inference.

All five complete 300/s attempts remain INCONCLUSIVE, with HTTP timeouts and
incomplete accepted-ID reconciliation. Acknowledgements are lower bounds, not
final backend acceptance counts. Reconciled timeouts in other trials also remain
HTTP failures: one 250/s four-replica trial had P95 536ms but failed the SLO because
158 requests timed out. P95 alone is insufficient. SQL observed zero violations;
capacity tests were pre-sale registration tests, not seat-booking throughput tests.

## Burst admission

Every trial used 10s at 5/s, 20s at peak, and 10s at 5/s, followed by the original
600s admission deadline. All nine completed trials passed delivery, unique IDs,
stable contiguous queue positions, terminal outcomes and SQL checks. All 27,900
offers were accepted. Admission includes terminal unavailable/expired outcomes,
not thousands of successful seat bookings.

| Peak | Offers / trial | Passing / complete trials | Mean admission (s) | Maximum admission (s) |
|---:|---:|---:|---:|---:|
| 100/s | 2,100 | 3 / 3 | 172.8 | 178.1 |
| 150/s | 3,100 | 3 / 3 | 263.9 | 269.7 |
| 200/s | 4,100 | 3 / 3 | 351.4 | 352.0 |

## Article, slides and raw evidence

- [Compact article table](../output/validation/followup-20261119/report/ARTICLE_TABLE.md)
- [Short Evaluation paragraph](../output/validation/followup-20261119/report/ARTICLE_EVALUATION.md)
- [Full results and denominators](../output/validation/followup-20261119/report/RESULTS.md)
- [Paired scheduler figure](../output/validation/followup-20261119/report/scheduler-paired-comparison.png)
- [Fresh HPA overview](../output/validation/followup-20261119/report/hpa-fresh-overview.png)
- [Offered/achieved, latency, HTTP failures and delivery figure](../output/validation/followup-20261119/report/traffic-offered-achieved.png)
- [Complete submission and evidence download](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest)

The figures also have editable SVG companions. Detailed per-cycle HPA timelines,
timestamped traffic, traces, logs, SQL checks, commands, source hashes, image IDs
and resource settings are retained. Every reported trial has a raw path in
`traffic-trials.csv`, `scheduler-policies.csv`, `hpa-summary.csv` or
`lab-provenance.csv`. The master continuation ledger maps all 64 units and the
historical interruptions. Per-run ledgers distinguish COMPLETE from outcome and
verify evidence hashes; interrupted attempts remain in separate directories.

The saved-data audit passed 1,046 checks with zero failures. Its remaining
interrupted cohort is the superseded, unmatched original F2 attempt; it is not
an unrun planned study. All 30 controlled unit evidence records and all 64 master
unit references were independently hash-verified. Measurement-harness versions are retained with the source hashes;
all workload schedules and acceptance thresholds were preserved;
legacy identity-read availability is inferred from saved queue snapshots when
the older summary predates that explicit flag. Raw files were not rewritten.
