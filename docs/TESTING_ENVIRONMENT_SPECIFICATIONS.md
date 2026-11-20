# Testing environment specifications and evidence

This document describes the recorded local environment for the completed follow-up evaluation and extended TC-14 baseline recorded in the exported evidence. Values come from saved trial snapshots, `output/validation/followup-20261119/report/lab-provenance.csv` and the TC-14 run export.

## Recorded follow-up environment

| Item | Recorded specification |
|---|---|
| Deployment | Local Kind Kubernetes cluster, context `kind-csc3104`, isolated namespace `csc3104-lab` |
| Runtime platform | Linux containers on Windows/WSL2; x86_64 |
| Linux kernel | `6.18.58.1-microsoft-standard-WSL2` |
| Docker Engine server | `29.9.3` |
| CPUs visible to Docker | 12 logical CPUs; this is not a physical core count |
| Memory visible to Docker | 8,259,383,296–8,259,387,392 bytes, approximately 7.69 GiB |
| Container storage / cgroups | `overlay2` / cgroup v2 |
| Kind client | `v0.33.0` |
| kubectl client | `v1.36.4`; this does not establish the Kubernetes server version |
| Application infrastructure | Ticket-booking services, PostgreSQL and Redis; exact deployed image IDs are retained per trial |
| Deployment provenance | Commit, working/application source hashes, image IDs, resource requests/limits, replica counts and configuration are recorded in the provenance CSV and raw snapshots |

The recorded memory values differ by only 4,096 bytes across snapshots. They describe Docker's visible environment, not the computer's installed physical RAM. Physical CPU model, installed host RAM, Windows edition/build and Docker Desktop application version are not established by these runtime fields.

## Experimental configuration

| Study | Configuration |
|---|---|
| Scheduler comparison | Demand-Cycle versus FCFS; matched seeds 42–51; 40 parties per trace; batch size 10; one allocation worker; 120-second hold TTL; sections A–D |
| Scheduler workloads | F1 balanced original baseline; F2 mostly single-person parties; F3 mostly four-person parties; F6 fragmented initial seating. Each policy pair uses the same trace and initial inventory |
| Capacity | Fixed waiting-room API replicas of 1, 2 or 4; follow-up offered rates 200, 250 and 300 requests/second; 30-second scheduled arrivals per trial; additional repetitions at selected boundaries |
| Burst load | 10 seconds at 5 requests/second, 20 seconds at a peak of 100, 150 or 200 requests/second, then 10 seconds at 5 requests/second; three completed trials per peak; 600-second admission deadline |
| HPA | CPU target 50% of requests; 1–4 replicas; at most one added pod per 30 seconds and one removed pod per 60 seconds; 60-second downscale stabilization |
| HPA CPU requests | Waiting-room API 50m; allocation worker 200m with 500m CPU limit. Worker HPA trials keep four fixed Ready API replicas |
| HPA phases | 120-second baseline, 180-second spike, 600-second zero-arrival recovery, repeated 180-second spike, 30-second final observation |
| HTTP generator | Up to 4,096 in-flight requests; 15-second request timeout. Delivery validity requires all scheduled requests launched, no generator drops and maximum launch lag at most one second |

Resource settings vary by service and experiment. Use the per-trial `resources` and `config` fields rather than applying one study's settings to every run.

### Extended TC-14 seat-store baseline

The five trials used the same `kind-csc3104` node and a fresh, isolated namespace per trial. Docker Engine 29.9.3 saw 12 logical CPUs and 8,259,383,296 bytes of memory. The node reported Kubernetes v1.36.4, and the host client used Python 3.11.0. Each trial deployed one Ready pod per component with a 300-second hold TTL and batch size 10. Seat API requests were 50m CPU and 96 MiB. Its limits were 500m CPU and 256 MiB. Each trial started with 200 available Section C seats and ran ten warm-ups and 100 measured single-seat requests at concurrency one. The [run environment](../output/tc14-extended-20261119/experiment.json), [per-trial snapshots](../output/tc14-extended-20261119/) and [methodology](TC14_EXTENDED_RESULTS.md) record the exact controls and evidence.

## Raw data and independent verification

The complete [submission release](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest) includes the raw evidence directly. The original sealed follow-up archive is retained as a provenance input:

`output/validation/followup-20261119/GROUP02_Followup_Final_20261119.zip`

Its saved export verification reports 2,802 files and 122,075,748 bytes. Recorded SHA256:

```text
de339c1c913baa25a785e987ba7c90991474089fa7e282f111eb58c0540a42b7
```

The archive contains the follow-up raw evidence and relevant original comparison baselines. It retains project-relative paths, including `.local/test-results/`. Per-trial files include customer outcomes, request traces, before/after snapshots, inventory records, traffic measurements and HPA timelines where applicable. The manifest records archived file hashes and any redaction. This document is a later explanatory addition and is outside the sealed archive.

The following files under `output/validation/followup-20261119/report/` are derived analysis tables, not substitutes for the raw observations:

| Files | Purpose |
|---|---|
| `scheduler-policies.csv`, `scheduler-strata.csv` | Per-policy results and party-size/section denominators |
| `scheduler-seed-deltas.csv`, `scheduler-section-pairs.csv` | Matched comparisons and variation across seeds/sections |
| `scheduler-summary.json` | Aggregate scheduler results and metric-specific sample counts |
| `traffic-trials.csv`, `traffic-timestamped.csv` | Per-trial load outcomes and timestamped traffic observations |
| `capacity-summary.json`, `burst-summary.json` | Capacity and burst summaries |
| `hpa-summary.csv`, `hpa-timeline.csv` | HPA outcomes and sampled scaling timelines |
| `lab-provenance.csv` | Runtime specifications and per-trial deployment identity/configuration |
| `RESULTS.md` | Analysis, definitions, limitations and paths back to raw runs |

Raw working copies also remain under `.local/test-results/`; this directory is local and may not accompany a Git clone. Share the existing evidence ZIP when raw evidence is needed.

## Interpretation limits

These experiments measure a shared local Kind/WSL2 environment. Adding pods shares the same host resources; the results do not establish multi-node or production-cloud scalability. Generator limits, host contention, HTTP timeouts and unreconciled backend acceptance affect some capacity trials. Invalid-delivery, inconclusive and interrupted attempts remain explicitly labelled and must not be pooled into passing samples.

All 64 planned follow-up units are complete, but completion does not mean every trial passed its SLO. Scheduler benefits are workload-dependent; fairness metrics have different eligible sample counts. The reported comparisons are descriptive and do not establish statistical significance.

No evaluation was rerun, image rebuilt or evidence archive recreated to prepare this document.
