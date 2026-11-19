# Evaluation matrix and experimental contracts

<!-- followup-20261119:later-evidence:start -->
**Later measured evidence - 19 November 2026:** [The completed local follow-up](../docs/FOLLOWUP_EVALUATION_RESULTS.md) adds F2/F3/F6 policy comparisons, repeated CPU-based HPA, higher-rate API capacity and burst admission results. The November 8 plan/audit below remains historical. Its broader cloud-cost, multi-node, production and larger-sample proposals are not certified by these local measurements.
<!-- followup-20261119:later-evidence:end -->

**Historical research plan:** the proposed experiments and targets below belong
to the 8 November source revision. They are not the current 25-case result ledger.
See the [current evidence index](../docs/VALIDATION_EVIDENCE.md) for the completed
local acceptance scope. Passing those 25 cases does not certify every additional
proposal here, including public-cloud cost and production HA/security work.

This follows the source audit in `ARCHITECTURE_AUDIT.md`. All experiments below are **proposed**, not passed or benchmarked. They apply to revision `8a777c3f5158de3d7be7c74b2fd000450f177cf2`. No numeric performance improvement is assumed. Phase 4 requires deployment-specific instrumentation and runnable drivers after the runtime blockers are resolved; existing executable starting points are identified rather than presented as a completed benchmark harness.

## Core experiments and lecturer feedback coverage

Updated following the lecturer feedback supplied on 8 November 2026. The five original experiments remain useful; E6 (disconnect/reconnect) and E7 (cost/autoscaling) are now explicit additions. E2 includes combined failures and E4 includes a sudden spike. All remain planned, not demonstrated.

| Lecturer feedback | Required experiment | Evidence to present |
| --- | --- | --- |
| Sudden influx | E4: steady load, abrupt spike, then return to baseline | Offered/successful rate, p95/p99, errors, backlog and recovery time |
| One or more services down | E2: individual and selected combined failures | User-visible behavior, preserved records, safety, restart/progress/drain times |
| Users leave and return | E6: reconnect at every important lifecycle state | Same request identity, current state, preserved queue position/deadline and no duplicate effect |
| Quantify fairness | E5: paired Demand-Cycle versus correct FCFS | Per-size acceptance, wait/displacement distributions and seat utilisation |
| Cloud cost and demand scaling | E7: fixed versus dynamic capacity and cost accounting | SLO, replica/node timeline, cost breakdown and cost per completed booking; measured versus estimated labels |

Execution order: deployment/functional gate; E1 correctness; E6 reconnect; E2 recovery; E4 influx; E3 worker scaling; E5 policy comparison; E7 cost comparison. Reuse controlled performance runs for cost accounting. Security boundary checks remain a release gate, especially before public exposure.

## Original five experiments

Order reflects assessment relevance, evidential value and reuse of existing tests. Effort is an estimate for a working local environment, not a delivery guarantee.

| Rank | Experiment | Concepts and hypothesis | Independent variable / fair baseline | Primary metrics | Required success / informative contradiction | Rubric relevance; effort |
| --- | --- | --- | --- | --- | --- | --- |
| 1 / E1 | Whole-party correctness under contention and lifecycle races | Transactional ownership and same-ID replay preserve invariants under concurrent requests | 1, 2, 8, 16, 32 clients; sequential correct implementation as reference; same trace and DB fixture | Invariant violations, unique winners/holds, duplicate effects, terminal outcomes, latency/errors | Zero overlap, partial parties, duplicate live holds, deadline extensions and contradictory lifecycle states; timeout/503 must not become false no-seat success | Concurrency and working functionality; low-medium |
| 2 / E2 | Recovery across commit/response/crash windows | Durable jobs/outboxes plus idempotency recover accepted work without repeating effects | Identical trace, healthy run vs crash/outage; one worker vs surviving replacement; explicit short and beyond-deadline outages | Lost accepted work, duplicate effects, lease-reclaim delay, time to first progress, backlog-drain time, unresolved jobs | Zero safety violations; bounded progress after dependency recovery or explicit BLOCKED diagnosis. Beyond-deadline work must expire/reconcile honestly | Partial failure, callbacks, recovery; medium-high |
| 3 / E3 | Useful worker scaling and its limits | Cross-section processing can benefit from shared workers; skew and locks bound speedup | 1, 2, 3, 4, 8 allocator workers, balanced A-D vs all-A; fixed API/DB resources and policy | Terminal jobs/s, successful held seats/s, batch makespan, p95 end-to-end delay, CPU-seconds/job, lock waits | Measured improvement under balanced demand supports benefit. Flat/all-A or regression beyond four explains limits; correctness must hold in every configuration | Cloud/distributed execution and quantitative performance; medium |
| 4 / E4 | Shared admission/API scale-out under rising arrival rate | Redis atomicity permits multiple APIs while preserving queue identity/order | 1 vs 2 vs 4 waiting-room API Pods; same Redis and traffic; API-only and frontend-proxied runs separately | Offered/admitted/failed rate, p50/p95/p99 registration and lookup delay, duplicates/gaps, per-Pod hits, Redis/CPU/memory | No invariant regression; higher sustainable **successful** request rate within the same declared latency/error target. No increase or saturation disproves capacity benefit in that range | Concurrency, service discovery, load distribution; medium-high |
| 5 / E5 | Demand-Cycle versus correct FCFS | Policy changes allocation outcomes across party sizes; benefits may trade off with queue order/utilisation | Policy only: implemented Demand-Cycle vs FCFS within each section of the same fixed batch; identical first-fit seat store, trace, seed and lifecycle | Party success by size, confirmed seats/capacity, adjacent block distribution, order displacement, wait distributions, scheduler time | Report wins, losses and neutral cases. Better average success with severe minority starvation or reduced utilisation does not justify unconditional fairness claims | Original contribution, quantitative comparison and related-work argument; medium-high |

Do not compare the safe implementation against an intentionally race-prone allocator as the principal performance baseline. A broken baseline can demonstrate a bug, not establish that distribution is beneficial. Do not replace the current app with a new monolith merely to create a comparison: one-worker and correct FCFS comparisons isolate meaningful decisions with less implementation confounding.

## Shared methodology and result format

- Use a dedicated lab and separate test databases. Save explicit kubeconfig/context/namespace, commit and dirty diff, image IDs/digests, runtime/dependency versions, node count, host CPU/RAM, Docker/WSL allocation, resource requests/limits, API processes/threads, worker replicas and database settings. Do not export secrets or `kubectl get secret -o yaml` into reports.
- Separate local single-node experiments from multi-machine/cloud claims. Save the load generator's host placement and utilisation; resource contention with the system can cap measured throughput.
- Each trial starts from an equivalent fixture. Restarting a service does not clear bookings, lottery, queue history, retries or caches. The application has one inventory, without `sale_id`; independent trials need isolated state. Reset only a verified disposable lab.
- For performance, use at least five independent paired trials/configuration, randomise configuration order and reserve a separate warm-up (initial target 30 seconds). Use a 120-second measured interval for steady-state API tests after a pilot checks feasibility. For finite sold-out allocation traces, warm code/connections separately, reset the fixture and measure trace completion; do not pretend a finite stock workload is stationary.
- For policy comparisons use at least 30 fixed seeds/scenario, paired across policies. For race tests use repeated fresh fixtures, initially 100 rounds per condition. These are experiment design choices, not proofs that rare failures cannot occur.
- Record individual durations with a monotonic clock. A multi-host event timeline needs clock-offset checks or a single observing clock; database timestamps are useful for authoritative deadlines, not automatically comparable to client clocks.
- Save all outcomes, including timeouts, 429, 5xx, retries, BLOCKED states and unfinished requests. Separate offered rate, HTTP success rate, accepted unique users, terminal jobs/s and confirmed bookings/s. Report latency of successes separately from errors/timeouts, plus incomplete/censored workflow counts.
- For E4 use a paced arrival schedule and record missed starts/queueing at the generator. A closed-loop thread-pool test is a useful saturation probe but does not maintain a fixed offered arrival rate as responses slow. Use separate registration and realistic lookup/poll mixes.
- Save `metadata.json`, `requests.jsonl` (trial/trace/request/operation/start/duration/status/attempt/outcome), `events.jsonl`, `resources.csv`, invariant counts and `summary.json` per run. Include worker/Pod IDs for distribution analysis; avoid bearer tokens and personal data.
- Resource samples: CPU/memory for generator, APIs/workers, Redis and PostgreSQL; active connections, lock waits and backlog age. `kubectl top` alone cannot establish peak CPU or CPU-seconds. If metrics-server is absent, record that limitation rather than fabricate samples.
- Summarise each trial separately, then compare paired differences and confidence intervals across trials. Do not treat thousands of correlated requests from one trial as thousands of independent replications. Publish median and trial range when five trials give imprecise intervals.

Provisional SLO for API capacity comparisons: at least 99% successful intended responses and p95 <=1 second during the measured interval, with no correctness violations and no steadily growing unresolved backlog for workloads that require completion. This is a **proposed coursework target**, not an official rubric threshold or a measured system capability. Validate it against the intended demo, fixed payment quotas and pilot data before using it. An expected sold-out outcome is a business result, not necessarily an HTTP or correctness error.

## E1 execution contract: correctness first

Prerequisites: supported Python plus dependencies, real dedicated PostgreSQL `*_test` database and Redis for the distributed queue tests. Existing fixtures create/drop randomly named schemas and must retain their database-name safety checks. Run suites in separate Python processes because legacy `app`/`db` imports collide.

Existing starting commands, from repository root (after environment repair):

```powershell
.\test.ps1
.\.venv\Scripts\python.exe -m pytest tests/test_lab_reset.py -q
.\.venv\Scripts\python.exe -m unittest discover -s src/allocation/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s src/batch-dispatcher/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s src/services/waiting-room/tests -v
.\.venv\Scripts\python.exe -m pytest src/waitlist-payment/tests -q
# Supply TEST_DATABASE_URL through the environment; never put credentials in logs.
.\.venv\Scripts\python.exe -m pytest tests/test_booking_integration.py -q
node --test frontend/tests/recovery.test.cjs
```

Confirm Redis test setup/environment from its fixture before execution. Do not infer a Redis integration pass from skipped tests. Save each process's stdout/stderr, exit code, JUnit output where supported, and skipped/error counts. The root `test.ps1` covers health and seat-store, not all services.

Existing test anchors: `seat-store/tests/test_store.py` last-two-seat contention, concurrent duplicate holds, confirmation/expiry race, lock ordering/deadline checks, rollback; `test_cancellation.py` confirmation/cancel race; payment tests for simultaneous attempt keys and callbacks; waiting Redis tests for duplicate users and concurrent claims. Allocation's current QueueTests use SQLite and mock holds: rerun equivalent claims against PostgreSQL and networked seat-store before claiming deployed worker correctness.

Extend these starting tests into traceable repeated runs: 16 clients race for the final two seats using party size 2 (exactly one winner); repeat the same request concurrently (one hold ID and original expiry); race confirm/cancel/expiry (one compatible authoritative terminal state, complete party); inject transaction/outbox failure (whole rollback). Check adjacency in one row, party cardinality, unique active ownership, hold-seat state agreement and payment projection convergence after recovery. Directly inspect current ownership, not only historical `hold_seats` links, which legitimately retain history.

Visual: table of attempted rounds/operations and violation counts by scenario; latency versus contention as a secondary chart. Any invariant violation fails the correctness gate. No observed violations bounds only the tested workload; distinguish stochastic interleavings from a formal correctness proof.

## E2 execution contract: crash windows and recovery

Run only in an explicitly identified disposable lab. Begin with the E1 integration tests for lost responses and stale claims, then use actual process/Pod and network failures. Existing `tests/docker_booking_smoke.py`, `demo.py --kubernetes --verify` and `infra/k8s/README.md` provide deployed acceptance starting points after Docker is available; they are not complete E2 timing instrumentation.

Required phases for each trial: initialise identical trace; observe durable acceptance; synchronise fault injection to a named boundary; record fault time; observe outage; restore dependencies; wait for terminal outcomes or the predeclared timeout; capture DB/job/outbox state and invariant results. Random Pod deletion alone does not prove that the target boundary was exercised.

Boundaries: (a) allocation claim before hold, (b) hold commit before allocator ack, (c) seat release/outbox commit before callback ack, (d) accepted payment before worker completion, (e) dispatcher claim/submission commit before reply. Use test-controlled barriers or a bounded response-dropping proxy to show a commit actually occurred; an application exception before sending is not lost-response testing.

Exercise individual allocation-worker, dispatcher-worker, payment-worker/API, seat-store API, Redis and PostgreSQL outages in separate trials. Then test at least allocation-worker + payment-worker failure and dispatcher-worker + payment-API failure. Record which operations remain available and which pause or fail. Test a failed replica with a surviving replica separately from an entire service outage; those are different availability claims. Begin with healthy traffic, inject the bounded failure, restore services and verify eventual state. Do not require normal availability while a singleton authoritative store is down; require honest failure responses and no corrupted or invented state.

Fault durations initially: 5 seconds, 40 seconds, and beyond the 300-second hold deadline. Allocation/payment claims are 30 seconds; dispatcher claims are 60 seconds. Record actual timings. A test must not demand confirmation after the deadline: safe expiry is a correct outcome, and global indefinite BLOCKED admission is an availability limitation to investigate.

Controls: same workload/fixtures/resources/lease settings, no unrelated resets or policy changes, healthy paired trial, bounded injection and fixed recovery observation window. A paused worker followed by a replacement and then resumed stale worker tests fencing; a terminated worker alone cannot test a late stale acknowledgment.

Success: zero duplicated business effects/lost durable records; queued progress after recovery; all terminal projections agree with authoritative seat state. For short recoverable failures use a provisional 120-second post-restoration observation bound for a small fixture, motivated by leases, polling and retry delays. A miss is a failed proposed recovery target or inconclusive if instrumentation fails; it must not be hidden by lengthening the bound after seeing results. Long-outage terminal reconciliation needs an explicit implementation contract before a pass is possible.

Visual: fault/progress/backlog timeline, recovery-duration distributions and an outcome table. Report recovery time from fault and from restoration separately; separate component restart from accepted-job completion.

## E3 execution contract: worker scalability

Use PostgreSQL-backed jobs, real seat-store and fixed batch size 50 first. Replay identical valid snapshots under each replica count; isolate one batch from dispatcher effects, then validate complete dispatcher-driven journeys separately. Use balanced A-D, 90% A and 100% A scenarios; independently vary party sizes. Keep service concurrency, resources, inventory and database settings constant. Use evaluation inventory (400 seats) in a fresh database when appropriate; seeding another tier into an existing dev database is intentionally rejected.

Measure finite batch start-to-terminal makespan and terminal jobs/s; label RESERVED/UNAVAILABLE counts. Do not benchmark mostly sold-out fast failures as successful booking throughput. Include an intentionally capacity-insufficient scenario separately. Keep actual payment and hold-expiry behavior equal across replicas; an optional artificial hold delay can diagnose coordination but is a synthetic microbenchmark, not an application performance result.

Two resource comparisons are useful: fixed per-worker limits (total resources increase with replicas), and fixed total worker CPU budget divided across replicas. Keep their conclusions separate. Let `X_n` be equivalent-work terminal throughput: speedup `S_n=X_n/X_1`, efficiency `E_n=S_n/n`; for finite identical traces speedup can also use `T_1/T_n`. Report useful held/confirmed seats as a separate denominator.

Collect per-worker completed IDs, scheduler-lock wait, active connections, worker idle time, seat-store transaction time and CPU/memory. More replicas without more simultaneously eligible sections can increase overhead. Work stealing across sections can help a balanced workload but cannot remove all-A serialisation. Zero or negative gain is an informative finding if the generator and fixtures are controlled.

Visual: speedup versus workers (ideal line for reference), makespan by section skew and CPU-seconds/job. Runtime distribution over Pods is not itself speedup. Restore original replica counts at trial end.

## E4 execution contract: admission, routing and overload

Vary only waiting-room API replicas first; keep Redis, dispatcher and worker settings fixed. Separate pre-sale registration from sale-opening and late-entry operation. Use duplicate-user bursts, sale-open boundary races and one-request polling in addition to unique registrations. Explicitly test opening interrupted partway through the bounded Lua chunks.

Start with 1/10/50/100/200 offered requests/s after pilot calibration, and concurrency caps chosen to avoid saturating the generator. Record achieved offered rate; if the generator misses its schedule, the high-rate condition is not a valid server capacity measurement. Compare `/requests/<id>` polling with `/status` as separate experiments, because aggregate state reads grow with retained queue size.

Add an abrupt spike trial: 60 seconds at baseline B, immediately 30 seconds at 5B, then 120 seconds back at B, after separate warm-up. Select B using a pilot showing stable baseline operation; select a safe bounded peak if 5B exceeds generator capacity. Repeat the identical schedule across replica configurations. Record the time until latency/error rate and backlog return to the predeclared acceptable range, with unfinished work reported at the end. Keep this transient response separate from steady-state capacity. Include sale-opening bursts and user retries, recording unique identities so retries cannot inflate admission goodput.

Existing `waiting-room/tools/load.py --mode register|poll --requests N --concurrency C` is an exploratory probe. A Phase 4 driver must add paced starts, raw records, independent section/size sampling, repeated trials and metadata. Use a verified lab URL only: registration changes state. Do not point it at the default EKS context or a shared customer/demo inventory.

For Kubernetes routing, send traffic via the waiting-room **Service** from a dedicated in-cluster generator. Port-forwarding a Deployment selects a Pod and cannot establish Service load balancing. Use temporary Pod identity/access-log instrumentation and multiple new connections; HTTP keep-alive and differing service times mean equal request counts are not guaranteed. Record hits, latency/errors and CPU per Pod. Then test via frontend separately to expose a possible proxy bottleneck.

Success for correctness: unique user-to-request mapping, unique committed queue numbers, late entrants after initial lottery positions and no duplicate batch membership. Define observable gaps carefully if some requests failed: queue numbers cannot be judged solely from the successful responses collected by the client. Capacity benefit requires a higher sustainable goodput at the same target and resources; flat throughput with rising Redis/CAS contention is evidence of the limit.

Visual: offered rate versus successful rate and p95/p99, error-status mix, per-Pod utilisation; annotate saturation and generator limits.

## E5 execution contract: policy benefit and fairness

First implement a reproducible policy comparison runner; no correct FCFS comparison runner was found. Reuse `prepare_batch` for Demand-Cycle, and change only intra-section ordering for the baseline. Keep fixed admission batches, first-fit adjacent placement, database guarantees, seat geometry and lifecycle identical. Sorting every batch globally or changing inventory locks at the same time would confound the policy comparison.

Scenarios: uniform sizes, strongly size-1 skewed, strongly size-4 skewed, equal-demand ties, balanced/skewed sections, near-capacity maps and deliberately fragmented maps. Arrival counts/party sizes/sections must be sampled independently and saved. Replay at least 30 paired seeds/scenario with an identical precomputed post-lottery queue so unseeded `SystemRandom` in the live lottery cannot confound policy ordering.

Start with all successful holds confirmed at fixed scripted think times and a fixed logical trace for pure policy simulation; clearly label simulated results. Validate selected traces against the actual PostgreSQL/HTTP system. Add abandonment/payment timing only as a separate factor; otherwise the slowest configuration may expire more holds and appear to have a different policy outcome. Preserve empty/full cases and zero-denominator sizes as N/A.

Predeclare fairness definitions. Report per-size party acceptance `accepted_parties_s / offered_parties_s`, seat utilisation `confirmed_seats / total_seats`, queue displacement and success by queue-position quantile. A Jain index across per-size acceptance fractions is only an optional summary (exclude absent sizes and define all-zero case); it does not replace counts, waiting tails or explain which group loses. Counting seats by size alone rewards large parties; counting total parties alone rewards small parties.

Hypothesis: Demand-Cycle may alter representation among size groups without violating adjacency/ownership. Contradictions include worse representation of the intended group, lower utilisation, increased displacement or longer tail waits. Demand sorting and cycling do not guarantee optimal packing or starvation freedom across all batches. Report paired differences and confidence intervals; effects spanning zero are inconclusive at that precision. A policy-only simulator cannot establish cloud speedup or network recovery.

Visual: per-size acceptance with paired intervals, utilisation versus fairness/displacement and queue-wait distributions. The paper must explain why the chosen fairness objective matters for this ticketing use case and compare it with actual cited prior work before claiming novelty.

## E6 execution contract: users disconnect and return

Objective: determine whether a returning browser recovers its original request without a new queue opportunity, duplicate payment or extended reservation. This is reconnect testing; the current rejoin route returns 410 and does not promise new admission after a terminal outcome.

Use the actual frontend with isolated test users and save request/hold IDs, queue number, original deadline and authoritative states. For each case capture state before disconnect, close/reload the tab or interrupt the client connection, allow the normal workers to continue, then return with the same stored identity. Cover pre-sale registration, queued admission, allocation in progress, active unpaid hold, pending payment, confirmed booking, expired hold, cancelled request and unavailable outcome. Repeat payment/cancel after a deliberately lost response using the same operation key. Include returning just before and just after the original deadline; use server-authoritative state rather than a browser countdown.

Controls: same user/request identity and workload, no new registration or reset during the disconnect, fixed worker/resources and declared disconnect duration. Separate preserved-browser-storage trials from cleared storage/new browser/device trials. If there is no authenticated identity recovery mechanism, record loss of identity recovery as a limitation rather than assuming an arbitrary user_id establishes ownership. Test different-user access separately as a security case.

Collect original/returned request IDs, queue positions, hold IDs/deadlines, unique attempts and final seat/payment states, discovery latency and user-visible messages. Pass requires no new queue position for the same recoverable request, no duplicate business effect, no deadline extension, accurate terminal-state display and preservation of confirmed bookings after unpaid-hold time passes. Returning after expiry must not restore the old seats. A clearly rejected unsupported recovery path is a documented limitation, not proof of seamless recovery.

Start from existing `frontend/tests/recovery.test.cjs` and waiting-room `tests/test_checkout.py`, then perform the browser/network scenarios against the deployed stack; those unit/adapter tests alone do not establish end-to-end reconnect behavior. Save a scenario table and selected screenshots/timeline linked to run IDs. Begin with at least five fresh-user repetitions per state and more around race/deadline boundaries.

## E7 execution contract: cost and demand-based scaling

Objective: quantify resources and monetary cost needed to deliver the same declared service target. Compare fixed capacity with the optional payment API HPA only after confirming it is deployed and receiving metrics. This HPA does not scale allocator workers or automatically demonstrate node autoscaling.

Replay an identical idle -> normal -> peak -> normal -> idle arrival trace for fixed-small, fixed-peak and HPA configurations. Hold database, business logic, payment quotas, fixtures, instance types and observation period constant. Use matched trials, record desired/ready API replicas, Pod/node placement, actual node counts, utilisation, scaling delays, successful booking completions, p95 latency and errors. If the whole-system bottleneck is elsewhere, API scaling can increase cost without increasing useful throughput; retain that result.

Account separately for cluster/control-plane charges, node time, attached storage, load balancer time and relevant requests/network transfer. Verify current provider/region prices when conducting the analysis and record the price date, currency and billing basis. Calculate total cost as the sum of billable quantity times applicable rate, with fixed and variable charges visible; calculate cost per confirmed booking only when the denominator is nonzero. Separate list-price estimates, account credits and actual billed charges. Pod replicas fitting existing nodes may change utilisation without changing node charges; demonstrate any node change rather than infer it from replica count.

Success is meeting the same declared latency/error/completion target at lower cost or showing a quantified cost-performance trade-off. A cheaper configuration that loses requests or misses the target is not equivalent service. Include idle cost and scale-down behavior. Compare equal-duration runs with equivalent completed workload, and report remaining backlog rather than omitting unfinished bookings.

Local Kind experiments can measure resource/scaling behavior, but do not produce a cloud bill. If cloud/HPA execution is unavailable, produce an explicitly labelled estimate from observed resource requirements and stated deployment assumptions; leave actual elasticity and savings Not Demonstrated. No paid rollout is necessary merely to fill a results table. Present a stacked cost breakdown plus cost versus successful bookings and the replica/node timeline. Preserve the test configuration and pricing inputs with each result.

## Supporting checks and release gates

| Check | Variables and exact starting point | Evidence / decision rule | Scope and priority |
| --- | --- | --- | --- |
| Clean deployment and persistence | Clean checkout; build/init/start via `python demo.py`; local Kubernetes via `python demo.py --kubernetes --verify` after repairing Python/Docker | Save build/deploy output, smoke invariants, records before/after PostgreSQL/Redis Pod replacement, observed RPO/RTO | Required reproducibility gate; do not erase existing volumes to make it pass |
| Security boundary | Direct internal vs scoped customer vs frontend-proxy request; existing payment token/scope/tamper tests | Allowed identities succeed; missing/foreign/read-only/expired grants cannot mutate; frontend route must not grant service privilege | Source audit currently finds a failure at frontend; reproduce in lab and fix before public use |
| Payment overload/backpressure | Fixed legitimate hold fixture, configured shared quotas/pending limits/pool sizes; existing reliability tests | Track 429/503, Retry-After, accepted pending cap, pool waits, eventual completion and unextended deadlines | Keep protection test separate from raw service saturation; quotas shared across replicas are intentional |
| HPA prerequisites for E7 | Payment optional HPA only; verify metrics and target Deployment before fixed-vs-HPA trials | Save HPA metrics/desired/actual/ready replicas and cold-start times, goodput and tail latency | Cost analysis is required by lecturer feedback; live HPA results depend on a working setup; estimates must be labelled |
| Storage outage / restoration | Isolated Redis/PostgreSQL unavailable then restored; preserve durable fixtures | Honest error classification, no invented reservations, eventual reconciliation, data-loss boundary | Recovery, not HA; true node/storage-loss and backup restore require a separately provisioned environment |

## Converting measurements into the article

Do not draft completed findings until raw results exist. A compact Evaluation should allocate roughly 700-1,000 words and 2-3 multi-panel figures/table where the overall six-page article permits: setup/controls; correctness counts; balanced/skewed scaling; failure timeline; policy trade-offs; limitations. This is a suggested allocation, not a required section word count.

Compute throughput improvements as `100*(X_new/X_base - 1)`; latency reduction as `100*(L_base-L_new)/L_base`. State denominators and handle zero baselines explicitly. Use percentage **points** for differences between acceptance percentages. CPU efficiency requires measured consumed CPU time, not requested CPU. Report repeat count, spread/intervals, timeouts and incomplete work for every major claim.

For each result explain the observation, mechanism supported by logs/resources, relevant design decision and bounded conclusion. If a bottleneck is inferred rather than isolated experimentally, label it as an inference. Preserve failed trials and fix/retest under a new recorded revision. The final readiness table should cite actual run IDs; its present audit classifications must not be promoted merely because test scripts exist.
