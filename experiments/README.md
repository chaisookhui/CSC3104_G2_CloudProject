# Lab measurement and testing tools

<!-- followup-20261119:latest-results:start -->
**Latest measured follow-up - 19 November 2026:** [Results and evidence](../docs/FOLLOWUP_EVALUATION_RESULTS.md) cover 30 matched F2/F3/F6 scheduler pairs, four full HPA cycles, 21 capacity trials and nine burst trials. All bursts passed; capacity outcomes were mixed. Highest observed passing offers at 1/2/4 API replicas were 200/250/250 requests/s, with 3/3, 1/3 and 1/3 passing trials at those rates. The saved-data audit passed 1,046 checks with zero failures. The original 25-case baseline remains separate and unchanged.

No follow-up trial remains pending. The current main results report and instructions include dated follow-up supplements.
<!-- followup-20261119:latest-results:end -->

Recorded final local status: all 25 documented cases PASS, comprising 15 newly
verified cases plus 10 full-scope final v9 cases independently re-audited.
The evidence audit passed 77 new and 244 original-workload checks (321 total).
See the [current evidence index](../docs/VALIDATION_EVIDENCE.md); earlier bounded
executions remain historical, and local acceptance is not production reliability.

Start with [the assessor testing instructions](../output/pdf/GROUP02_INSTRUCTIONS.pdf).
They provide all eleven requested sections: architecture/setup, deployment,
functional/distributed/cloud tests, recovery, benchmarks, a summary matrix and cleanup.
The [editable text companion](../output/pdf/GROUP02_INSTRUCTIONS.md) contains the
same instructions. The earlier complete technical handbook is archived as a
historical document. Edit the current Markdown and render
it with `python experiments/build_instructions.py` using a reportlab-enabled runtime.

The main frontend intentionally contains no test-case workbench. Use Overview,
Batches, Seat map and My booking to observe the application at **http://127.0.0.1:18100**.
Use the PDF's TC-01 to TC-18 procedures and this CLI for execution/evidence.
TC-19 to TC-25 and [extended robustness procedures](ROBUSTNESS.md) add thousands
of arrivals, mixed parties, lifecycle races, committed-reply/crash recovery,
sustained dependency outages, API scaling, optional HPA and browser ownership.
For administrator controls run `python experiments/access.py --namespace csc3104-lab`
and use the page header's Administrator sign in. CLI experiments authenticate
with the namespace's local operator credential; they do not need browser login.
Historical IDs in older validation records differ from the current submission guide.

## Prepare the lab

Use host Python 3.10+; registration load uses the pinned async HTTP client.
Install it before running load experiments. Start Docker and run
from the repository root:

```powershell
python -m pip install -r experiments/requirements-load.txt
python demo.py --kubernetes --check
python demo.py --kubernetes
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
python infra/k8s/kubectl.py -n csc3104-lab port-forward --address 127.0.0.1 service/frontend 18100:8080
```

`--reset-lab` explicitly deletes only the lab namespace, its PVCs and its local
credentials before redeploying. Export old evidence first. It never targets main
`csc3104`. The normal lab command preserves records. Do not run two deployments or
experiments at once. Restart the browser port-forward after a reset.

The CLI makes its own temporary loopback port-forward and checks the actual
frontend namespace before workload execution. It does not trust the port number
alone. Kubernetes credentials and mutation commands are not exposed in the UI.
The separate `csc3104-check` namespace is also recognized as disposable for the
automated smoke harness; public operator commands remain fixed to `csc3104-lab`.

## Capture a manual test

```powershell
python experiments/run.py capture --case W1 --run W1-run1 --phase before
# Follow the PDF's TC-11 procedure. Restore the original worker count afterwards.
python experiments/run.py capture --case W1 --run W1-run1 --phase during
python experiments/run.py capture --case W1 --run W1-run1 --phase after
python experiments/run.py invariants --run W1-run1
```

Files are saved in `.local/test-results/<run-id>/`. Captures include configuration,
safe pod/PVC identifiers, replica requests/readiness, backlog and SQL checks where
available. They do not include Kubernetes Secrets or kubeconfig. Add screenshots
and a written observed-result record to the same evidence folder.

## Registration and direct contention

Use a fresh empty pre-sale lab **before every independent run**:

```powershell
python experiments/run.py register --rate 5 --duration 10 --run registration-baseline
# After a fresh lab reset:
python experiments/run.py register --rate 25 --duration 30 --profile spike --run registration-spike
# After another fresh reset:
python experiments/run.py contention --count 10 --workers 10 --run C1
```

Registration uses scheduled arrivals, retains generator drops/unknowns and
reconciles accepted IDs. It measures registration only, not bookings. The async
local tool is for controlled local experiments/calibration. Inspect launch lag
and generator drops before making a capacity claim.

Contention deliberately bypasses queue/allocator/payment and sends real overlapping
HTTP hold requests to Section C's ten seats. It measures client request overlap,
not the number of database transactions executing simultaneously. It checks real
PostgreSQL invariants. C1/C2/C3/C4 are 10/50/100/500 requests; calibrate before the
larger runs. Maximum client workers is 64.

## TC-14 extended seat-store baseline

With the project Kind cluster and images already available, run from the repository root:

```powershell
python experiments/tc14_extended.py --run tc14-extended-repro01
python experiments/tc14_report.py --run tc14-extended-repro01 --output output/tc14-repro01
```

The collector uses host Python 3.10+ and the project launcher. The offline exporter requires Matplotlib. Allow 5–10 minutes for deployment, measurement, SQL verification and cleanup. Use a new run ID and export directory each time. The collector creates one disposable namespace per trial and saves raw observations under `.local/test-results/<run-id>/`. Run without concurrent benchmarks or changes to the cluster. See the [protocol and recorded results](../docs/TC14_EXTENDED_RESULTS.md).

## Trace replay and equivalent FCFS

```powershell
python experiments/run.py trace --scenario F1 --count 40 --seed 42 --batch-size 10 --output .local/traces/F1-42.json
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
python experiments/run.py replay --trace .local/traces/F1-42.json --run journey-F1-42
```

For a paired comparison, the command **explicitly resets only the lab before each
policy**. Workload commands need a new run ID and capture before/after evidence
themselves. Do not pre-fill their run directory with manual capture files.

```powershell
python experiments/run.py compare --trace .local/traces/F1-42.json --reset-lab --hold-ttl 30 --replicas 1 --repeats 3 --run pair-F1-42
```

Policies use the same fixed-batch/per-section eligibility and worker model, with
unchanged seat selection, hold transactions and payment code. FCFS orders original
queue positions within each section/batch. It is not globally serial FCFS. The
normal main deployment always defaults to Demand-Cycle. Recorded batch policy is
durable; replaying a batch under another policy conflicts instead of silently
reusing a different schedule.

The trace saves identities, section, size, queue position, wave, action/delay and
batch size. The CLI applies the saved initial queue using a lab-only Redis fixture
before sale opening. Normal registration keeps its SystemRandom lottery. Late-wave
numbering is reproduced by sequential submission with dispatch briefly paused.
Actual queue positions, policy, batch membership and initial inventory are checked.

| Scenario | Setup |
| --- | --- |
| F1 | Balanced section/size pairs |
| F2 | 70% size 1, section independently chosen |
| F3 | 70% size 4, section independently chosen |
| F4 | 80% Section A, size independently chosen |
| F5 | 80% pre-filled confirmed inventory in each section |
| F6 | Alternating occupied/free positions; use `--hold-ttl 120` or longer for fixture preparation |
| F7 | First wave has confirm/cancel/expiry behavior; second wave arrives after release |

Inventory fixtures use seat-store-owned hold/confirm/cancel operations. Fingerprints
compare physical seat states, not generated hold UUIDs. Fixture bookings are
excluded from offered-customer denominators and reported separately in inventory
counts. Raw fixture records remain visible to safety checks.

Read `comparison.json` and per-policy `summary.json` for outcomes, section/size
sample counts, successful reservations/confirmations, missing outcomes and
median/P95 decision waits. For registration/contention HTTP samples, run
`python experiments/metrics.py --run <your-run-id>` to produce `metrics.json`
with mean/P95 latency, HTTP success/error/missing rates and throughput. This
does not turn a no-fit HTTP 200 response into a successful booking.

`--repeats` alternates policy order but repeats **one saved trace**. Generate at
least ten separate seeded traces where feasible for a research claim. Preserve
every pair, including inconclusive runs. Small smoke runs prove the tool can run,
not that Demand-Cycle is statistically fairer.

## Measurement semantics

- Decision timestamps are saved atomically with fenced allocator outcomes for
  both RESERVED and UNAVAILABLE. Eligibility comes from Redis. Synchronized clocks
  are required. Missing or negative timing is not fabricated as zero.
- Overtakes compare recorded decisions only within the same section and actual
  batch, including unsuccessful decisions.
- Replay jobs/s uses client-observed full replay time, including registration,
  actions and draining. It is not isolated allocator service throughput.
- Unknown/unfinished customers stay in the denominator and prevent a conclusive
  tool pass. Useful reservations and quick unavailable decisions remain separate.
- Six seat checks and two payment duplicate checks use real PostgreSQL. An empty
  hold history is `INCONCLUSIVE_EMPTY`, not proof of a contested booking test.
- HTTP latency in CLI captures is a client round trip. API health and a Ready
  worker pod do not establish useful progress. Missing metrics remain unavailable.

## Validation and limits

```powershell
python -m unittest discover -s tests -p test_experiments.py -v
node --test frontend/tests/recovery.test.cjs frontend/tests/access.test.cjs
# After current images are loaded; refuses an existing csc3104-check namespace:
python experiments/verify.py
```

The last command creates, resets and removes only its own disposable verification
namespace. It preserves main and the existing lab. See `VALIDATION.md` for actual
executions and evidence, rather than treating configured tests as recorded passes.

See [extended robustness procedures](ROBUSTNESS.md) for committed-reply/crash
injections, sustained dependency outages, API replicas, browser ownership and
optional HPA. The [current 25-case evidence index](../docs/VALIDATION_EVIDENCE.md)
selects completed final studies; `output/validation/robustness-results.md` retains
the earlier 12 November observations and incomplete studies. Verified personal accounts,
storage HA, node failure and allocator blocked-work repair remain outside this demo.
Cost analysis is excluded.

For the full surge repetitions, fixed-replica/capacity grids and automated HPA
baseline/spike/recovery/repeat cycle, use [the scaling study procedure](SCALING_STUDIES.md).

For the additional F2/F3/F6 seed comparisons, repeated HPA cycles and bounded
200/250/300 requests/s capacity grid, use [the follow-up procedure](FOLLOWUP_STUDIES.md).

`build_instructions.py` is the PDF renderer for the current editable submission
Markdown. Re-render and inspect the PDF after changes.
