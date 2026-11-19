# Additional scheduler, HPA and higher-load measurements

The 19 November follow-up is complete; see [final observed results](../docs/FOLLOWUP_EVALUATION_RESULTS.md). Do not repeat completed studies.

This procedure adds evidence to the original 25-case ledger. It does not replace
or recertify those original results. All deployed commands use the project's
dedicated Kind kubeconfig and only `csc3104-lab`. Run one experiment at a time.
Current cohort commands and outcomes live in
`output/validation/followup-20261119/`; raw runs use the same prefix under
`.local/test-results/`. An attempt is a measurement only after it actually runs.

## Preserve before resetting

```powershell
python experiments/preserve_lab.py --run followup-YYYYMMDD-preserve-a
```

This read-only export seals original run files and submission documents into a
verified ZIP, records hashes, captures existing lab observations/logs/inventory,
and exports the lab's four SQL databases and Redis records. Its snapshot is local
private evidence. It excludes Kubernetes Secrets and kubeconfig. Do not publish
the private original archive wholesale. A failed export does not authorize a reset.

## Execute the complete sequential cohort

```powershell
python experiments/followup.py --prefix followup-YYYYMMDD --preserved followup-YYYYMMDD-preserve-a --plan-only
python experiments/followup.py --prefix followup-YYYYMMDD --preserved followup-YYYYMMDD-preserve-a
```

The plan uses the existing public `run.py trace`, `run.py compare`, and `study.py`
commands. The orchestrator records commands, logs, interruptions and run IDs.
Completed identical attempts and incomplete evidence are retained. The November 19 cohort is complete; refer to its recorded results rather than rerunning it as a new experiment.

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

## Article tables and slide figures

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
## Current submission documents

The main results report and instructions include dated follow-up supplements. [Documentation synchronization](../docs/FOLLOWUP_DOCUMENTATION_UPDATE.md) records their page counts and checks. The article table/paragraph and slide PNG/SVG files remain in the report folder; these are insert-ready materials, not edits to a separate article manuscript or slide deck.
<!-- followup-20261119:documentation-link:end -->
