# Fair Seat Allocation
CSC3104 Cloud and Distributed Computing | Group 02

**Testing Instructions | 12 November 2026**

## 1. Introduction
This application allocates adjacent seats to parties of one to four people. Customers register for a sale, receive a queue position when the sale opens, and receive a whole-party reservation if a suitable block exists. A mock payment confirms the reservation. Unpaid reservations expire; customers can cancel an unpaid reservation. No money or real payment details are involved.

This document lets an examiner deploy the submitted source, test the implementation and retain evidence. Test procedures belong in this PDF and the CLI. The application provides Overview, Batches, Seat map and My booking for observing actual behavior, without displaying a test-case checklist.

**Implemented:** separate HTTP services; Redis atomic admission; PostgreSQL transactions and locks; fixed-batch scheduling; durable asynchronous allocation/payment jobs; leases and fenced acknowledgements; specific idempotent operations; retryable callbacks/outboxes; container orchestration; manual horizontal scaling; persistent local storage.

**Limits:** one inventory; single-node Kind cluster; no complete waitlist/rejoin workflow, consensus, cross-service atomic transaction or storage HA. The gateway enforces browser ownership and administrator access when its generated service credential is configured. This is a browser session, not a verified account or cross-device login. Keep access on localhost. Optional lab HPAs and fairness/scaling benefits require measured evidence; cost analysis is excluded.

### Recommended examination route
1. Sections 3-4: deploy and prepare the isolated lab.
2. TC-01 to TC-06: customer journeys and invalid input.
3. TC-07/08: service communication and concurrent seat safety.
4. TC-09/10 and TC-11/12/13/17: containers, orchestration and recovery.
5. TC-14/15/16/18: measured baseline, load, scaling and policy comparisons.
6. Section 10: record observed results; Section 11: preserve evidence and stop safely.

**Evidence labels:** Implemented means inspected in source. Expected is an acceptance condition, not a result. PASS requires execution and evidence. NOT RUN, BLOCKED, FAIL and INCONCLUSIVE remain distinct. No hold history means an inconclusive safety check, not a booking pass.

**Source basis:** service implementations, schemas/migrations, Dockerfiles, deployment configurations, launcher, frontend, tests and experiment tools in this checkout. The local four-page Project_2026-27.pdf assignment brief was reviewed. It requires containers and/or Kubernetes, tested advertised functionality and explicit testing instructions. This document is the testing guide, separate from the research article.

<!-- pagebreak -->
## 2. System Architecture
<!-- architecture -->

| Component / internal port | Responsibility and authoritative state |
|---|---|
| Frontend / 8080 | Static UI and HTTP proxy; no inventory authority. |
| Waiting room / 5001 + waiting-recovery | Redis registration/global queue; recover sale opening and dispatcher triggers. |
| Dispatcher API / 5005 + dispatcher-worker | Fixed batches, persisted handoff progress and completion receipts in dispatcher PostgreSQL database. |
| Allocation API / 5002 + allocation-worker | Demand-Cycle/FCFS order, leased jobs, outcomes and completion outbox in allocation PostgreSQL. |
| Seat API / 5003 + seat-worker | Earliest-row/leftmost adjacent blocks; transaction locks; holds, ownership/history and notification outbox in seats PostgreSQL. Expiry/callback housekeeping. |
| Payment API / 5004 + payment-worker | Mock attempts, checkout projections, cancellation, inbox and recovery work in payment PostgreSQL. Confirm exact holds through seat API. |
| PostgreSQL / 5432; Redis / 6379 | One of each; four SQL databases share one server. Redis AOF and Compose volumes/Kubernetes PVCs retain state. |

### Request and recovery flow
Browser > frontend > waiting room > Redis saves registration. Opening sale uses a pre-sale lottery; later arrivals receive subsequent queue positions. Dispatcher claims a fixed batch and sends it to allocation with saved handoff identity. Workers call seat-store; seat-store alone locks and chooses seats. Completion callbacks let dispatcher record queue outcomes. Checkout can discover an individual completed allocation before the full batch finishes.

Payment HTTP submission accepts work synchronously; a separate database-polled worker confirms the exact hold. Seat expiry releases unpaid seats and queues a notification in the same transaction. Callbacks can be delivered repeatedly: transport is at least once, with specific identities preventing repeated business effects. Redis and SQL projections can temporarily disagree while recovery runs.

### Deployment and useful parallelism
Compose runs frontend, five APIs, five workers, PostgreSQL and Redis, plus three init containers, using six application images. Kubernetes has eleven Deployments, two StatefulSets/PVCs, three Jobs, Services, ConfigMaps and namespace-specific Secrets. Initial replicas are one. APIs have probes; Ready workers alone do not prove progress.

At most one allocator job per section is active, so A-D permit at most four useful concurrent hold calls. BLOCKED work stops later jobs in that section and the next fixed batch. Additional replicas do not necessarily improve throughput. PVC persistence is not HA or a backup.

<!-- pagebreak -->
## 3. Prerequisites and Environment Setup
**Command environment:** Windows x64 PowerShell, repository root containing demo.py. Tool downloads also support Linux/macOS; printed shell instructions use PowerShell. Use a browser with JavaScript and local/session storage enabled. Node.js is optional for frontend unit checks.

| Requirement | Verification / details |
|---|---|
| Host Python 3.10+ | python --version. Launcher/network tools use standard libraries; app packages run inside images. |
| Docker Engine 24+ and Compose 2.20+ | docker version; docker compose version. Running Linux-container engine required. |
| Resources | At least 2 CPUs, 4 GiB Docker RAM; 8 GiB recommended. Several GiB disk for images/storage and headroom for two namespaces. |
| Kubernetes | Launcher installs checksum-verified Kind v0.33.0 and kubectl v1.36.4 in .local/bin. Pinned node image: infra/k8s/kind.yaml. |
| Internet | Needed initially for tools, images and Python packages. No paid cloud account/payment API key required. |
| Host ports | 18080 Compose main; 18090 Kubernetes main; 18100 lab. Store/API ports are internal; Kind also uses a local control-plane port. |

Run from repository root:
```powershell
Get-Item demo.py
python --version
docker version
docker compose version
python demo.py --kubernetes --check
```
Expected: demo.py exists, Docker server responds and final command reports Kubernetes prerequisites ready. The check may prepare pinned tools; it does not create a cluster. If Docker cannot connect, start Docker Desktop and wait for its Linux engine.

### Configuration and datasets
No manual credentials are needed for local startup. Compose generates ignored .env.core. Kubernetes generates .local/k8s/secrets-<namespace>.json and a Secret. Retain credentials with initialized storage. Do not copy another machine's .local directory or publish Secrets/kubeconfig. Editing a password file alone does not rotate the database password.

Relevant settings: HOLD_TTL_SECONDS=300, BATCH_SIZE=50 in main/10 in this lab, ALLOCATION_POLICY=demand-cycle or lab fcfs, WAITING_ROOM_STORAGE=redis, REDIS_URL, QUEUE_KEY, DATABASE_URL, ALLOCATION_DATABASE_URL, DISPATCHER_DATABASE_URL, PAYMENT_DATABASE_URL, PAYMENT_API_TOKEN and service URLs. See core.env.example and infra/k8s/local/config.yaml; launchers supply credentials and internal DNS addresses.

Development inventory: A=30, B=20, C=10, D=10, ten seats per row. Manual tests use fictional names; no upload required. F1-F7 traces are generated by documented commands with saved seeds.

**Runtime distinction:** Dockerfiles specify frontend Python 3.11, waiting room 3.12 and seat/allocation/dispatcher/payment 3.15.0. Host Python runs launchers. Native service development has separate setup.ps1/pinned dependency requirements and is unnecessary for the recommended container route.

<!-- pagebreak -->
## 4. Installation and Deployment
### A. Start the main system
In PowerShell Window A, repository root:
```powershell
python demo.py --kubernetes
python infra/k8s/kubectl.py -n csc3104 get pods,pvc,services,jobs
```
Expected: Local Kubernetes is ready at http://127.0.0.1:18090. APIs/workers become Running/Ready, postgres/redis PVCs become Bound and init Jobs become Complete. First builds/downloads can take several minutes. Open the address; Overview and My booking should be available. See Section 11 for failed Jobs, unavailable storage or image errors.

**Compose alternative:** run python demo.py, open http://127.0.0.1:18080 and inspect:
```powershell
docker compose --env-file .env.core -f compose.core.yaml ps -a
```
Running app/storage containers and init/migration exit code 0 are expected. Both paths preserve existing bookings. Avoid simultaneous stacks if resources are limited. Later destructive experiments use Kubernetes lab regardless of whether Compose is also demonstrated.
For Compose administrator sign-in, retrieve the password with python experiments/access.py --compose.

### B. Create the isolated examination lab
After A builds/loads images, run:
```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```
**This explicitly deletes previous csc3104-lab bookings, queue, PVCs and generated lab credentials. Save lab evidence first.** Main namespace/PVCs are separate. Expected: Lab ready. Define this namespace-fixed helper in Window A:
```powershell
function k { python infra/k8s/kubectl.py -n csc3104-lab @args }
k get pods,pvc,services,jobs
```
In PowerShell **Window B**, same repository root:
```powershell
python infra/k8s/kubectl.py -n csc3104-lab port-forward service/frontend 18100:8080
```
Leave B running after Forwarding from 127.0.0.1:18100. Open http://127.0.0.1:18100. In A:
```powershell
Invoke-RestMethod http://127.0.0.1:18100/api/demo/context
Invoke-RestMethod http://127.0.0.1:18100/api/waiting-room/status
```
Require namespace=csc3104-lab, is_lab=True, storage=redis, sale_state=pre_sale. Retrieve the local administrator password:
```powershell
python experiments/access.py --namespace csc3104-lab
```
Choose Administrator sign in in the page header to access Overview, Batches, Seat map and simulation controls. Seat map should have 70 available seats. Customers use browser-owned identities in My booking. Use a separate browser profile without admin access for TC-25. Main uses --namespace csc3104. Browser ownership lasts seven days; cleared cookies or a reset loses access.

**Reset rule:** repeat the lab reset before each independent load/capacity/fault run. Stop/restart B's forward after every reset, retrieve the new password, sign in again and choose My booking > New user. Old browser identities may reference deleted records. Never run two deployment/experiment commands concurrently. CLI tools create their own temporary forwards and read local operator credentials; unique --run IDs preserve evidence.

<!-- pagebreak -->
## 5. Functional Testing
Use lab port 18100. Keep Overview in tab A and My booking in tab B. Record observed status, IDs, evidence filenames and differences from expectations.

### TC-01 | Register, allocate and confirm
**Objective:** verify the complete normal booking path.
**Preconditions:** clean five-minute lab, pre-sale.
**Test Data:** Alice Test, Section A, party size 2.
**Steps:**
1. My booking > New user; enter Alice Test > Continue; choose A/2 > Register once. Record User ID and Request ID.
2. Overview > Start sale once. Wait for RESERVED / Seats reserved; record Hold ID, seat labels and Pay before.
3. Complete mock payment before the deadline; wait for CONFIRMED. Refresh Seat map; reload customer.
4. In Window A:
```powershell
python experiments/run.py invariants --run TC-01
```
**Expected Result:** exactly two adjacent seats in one row confirmed for the same request/hold; reload preserves identity and result.
**Verification Method:** compare original/final seats and IDs; invariant status=PASS, violations=0 and nonempty hold history.
**Evidence:** booking/seat-map screenshots and .local/test-results/TC-01/invariants-*.json.

### TC-02 | Decline then retry
**Objective:** verify decline does not confirm seats or renew the payment window.
**Preconditions:** sale open, free Section B seats.
**Test Data:** Bob Decline, B/2.
**Steps:**
1. Create/register Bob; wait for RESERVED and record hold/deadline.
2. Simulate decline; wait until the attempt finishes. Check seats remain held/unconfirmed.
3. Before the original deadline, Complete mock payment; wait for CONFIRMED; refresh seats.
**Expected Result:** retry confirms the same hold without extending the original deadline.
**Verification Method:** compare original hold/deadline and final seats. Repeated clicks during pending processing replay the pending action.
**Evidence:** declined/final checkout screenshots, hold/deadline and attempt IDs.

### TC-03 | Cancel unpaid seats
**Objective:** verify whole-party release and terminal cancellation.
**Preconditions:** sale open, free C capacity.
**Test Data:** Carol Cancel, C/3.
**Steps:**
1. Create/register Carol; wait for RESERVED; record all three seats and hold.
2. Cancel reservation; accept confirmation; wait for CANCELLED.
3. Refresh Seat map and reload Carol. Run the TC-01 invariant command with --run TC-03.
**Expected Result:** all three seats available; same cancelled booking remains terminal and cannot pay.
**Verification Method:** compare all original seats, backend checkout and invariant PASS.
**Evidence:** before/after customer and seat-map screenshots; invariant JSON.

<!-- pagebreak -->
## 5. Functional Testing (continued)
### TC-04 | Expiry and late-payment rejection
**Objective:** verify backend expiry and rejection of a late payment.
**Preconditions:** five-minute lab, sale open, free D seats.
**Test Data:** Dan Expiry, D/1, no payment.
**Steps:**
1. Register Dan; record RESERVED hold/seat/deadline.
2. Wait beyond Pay before without payment/cancellation; allow housekeeping.
3. Reload customer and refresh seats until backend checkout reports EXPIRED.
4. For an actual late-payment HTTP check plus duplicate registration/payment/cancellation assertions, save evidence and run:
```powershell
python demo.py --kubernetes --verify
```
**Expected Result:** expired party is released and remains expired; actual late payment receives HTTP 409. Checker exits successfully only if its assertions pass.
**Verification Method:** backend terminal status, released seat and checker PASS output. A zero countdown alone is insufficient.
**Evidence:** screenshots and saved terminal output. Checker creates/deletes only csc3104-check for acceptance, then deploys main without resetting main PVCs. Requires absent check namespace; do not overlap other deployments.

### TC-05 | Whole-party capacity and tab recovery
**Objective:** reject partial parties and recover stable identities.
**Preconditions:** reset lab per Section 4, restart B forward.
**Test Data:** C1, C2, C3, each C/4.
**Steps:**
1. Register three new customers before sale; open sale. Inspect each through My booking > View an existing user > View user.
2. Before holds expire, refresh Seat map and record all outcomes.
3. Keep Overview in one tab; open a reserved customer in two other tabs through the picker; reload both.
4. Run invariants with --run TC-05.
**Expected Result:** at most two C/4 parties reserve; another gets UNAVAILABLE with no partial party. With all healthy fresh runs, eight seats are held and two remain free. Winner identity depends on policy/order. Tabs retain selected view; same-user tabs recover identical IDs/seats/deadline.
**Verification Method:** three outcomes, exact seat counts, original/restored identities and invariant PASS.
**Evidence:** customer/seat/reload screenshots and invariant JSON.

### TC-06 | Invalid inputs and unknown IDs
**Objective:** test backend validation beyond browser restrictions.
**Preconditions:** reachable lab; no other registration writers.
**Test Data:** sizes 0/5/true; section Z; empty user; missing fields; nonexistent request.
**Steps:**
```powershell
python tests/http_validation_smoke.py --base-url http://127.0.0.1:18100
```
**Expected Result:** six invalid registrations return HTTP 400; unknown request/section reads return 404; queue count unchanged.
**Verification Method:** assertions, status=PASS and exit code 0. Transport errors/assertion failures are not passes.
**Evidence:** saved terminal JSON. Script never opens a sale or books seats.

<!-- pagebreak -->
## 6. Distributed Systems Testing
### TC-07 | Communication and asynchronous lifecycle
**Objective:** trace actual work through services.
**Preconditions:** reset lab; perform a fresh TC-01 journey.
**Test Data:** new A/2 party plus four simulated B/1 parties; record request/batch/hold IDs.
**Steps:**
1. Before registration, capture:
```powershell
python experiments/run.py capture --case TC-07 --run TC-07 --phase before
```
2. Perform TC-01. In Overview/Batches compare request/batch IDs, section demand, priority, state and seats with My booking.
3. After confirmation, Overview > Simulate users: How many=4, Section=B, Party size=1 > Add users once. Expect four added sim-... users tagged latecomer; wait for their allocation outcomes without pressing Start sale again.
4. Capture and inspect:
```powershell
python experiments/run.py capture --case TC-07 --run TC-07 --phase after
k logs deployment/allocation-worker --tail=80
k exec deployment/payment-worker -- python service.py monitor
```
**Expected Result:** original A/2 confirms; four B/1 simulated registrations each reach RESERVED automatically. Queue has five distinct requests. Completion notification eventually becomes delivered, subject to retries.
**Verification Method:** correlate IDs, queue/backlog, worker logs and booking. TC-11 makes the asynchronous pending phase directly observable.
**Evidence:** before/after captures, Batches/customer screenshots and logs. Captures combine multiple times, not one distributed transaction.

### TC-08 | Concurrent contention and consistency
**Objective:** verify atomic seat ownership under simultaneous HTTP requests.
**Preconditions:** reset lab, fresh ten-seat C, no other writers.
**Test Data:** 20 distinct single-seat requests; 20 client threads.
**Steps:**
```powershell
python experiments/run.py contention --count 20 --workers 20 --run TC-08
python experiments/metrics.py --run TC-08
python experiments/run.py invariants --run TC-08
```
**Expected Result:** exactly ten RESERVED, ten UNAVAILABLE, no UNKNOWN, peak_overlapping_client_requests>=2 and zero invariant violations. No overlapping live ownership.
**Verification Method:** compare summary.json, customers.json/csv and inventory-before/after.json. The tool's broader safety PASS is insufficient if these stricter assessor expectations fail.
**Evidence:** .local/test-results/TC-08/. Overlapping client HTTP lifetimes do not imply 20 simultaneous SQL transactions. This test bypasses queue/allocator/payment to stress authoritative seat transactions.

**Consistency evidence:** six seat checks cover free-seat ownership, state/hold agreement, whole live parties, adjacency, duplicate live requests and overlapping live seat histories. Two payment checks detect duplicate pending/successful attempts. INCONCLUSIVE_EMPTY is not a passed booking check.

**Implementation explanation:** request advisory locks plus section row locks protect seat transactions across processes; constraints enforce ownership. Allocator leases/token checks fence acknowledgements, while seat idempotency protects repeated remote calls. TC-04's isolated network checker repeats registration, same-key payment and cancellation; it verifies stable saved identities. Delivery is at least once, not exactly once.

<!-- pagebreak -->
## 7. Cloud-Native Testing
### TC-09 | Docker startup and networking
**Objective:** confirm container startup and service-to-service routing.
**Preconditions:** Docker running; preserve existing Compose bookings.
**Test Data:** submitted compose.core.yaml.
**Steps:**
```powershell
python demo.py
docker compose --env-file .env.core -f compose.core.yaml ps -a
docker compose --env-file .env.core -f compose.core.yaml logs --tail 40
Invoke-RestMethod http://127.0.0.1:18080/api/seats/health
```
**Expected Result:** app/storage containers run, init containers exit 0 and health reports seat-store/postgresql. Only frontend loopback port is published.
**Verification Method:** ps/logs match Compose services; proxy health verifies internal container DNS/routing. TC-04 exercises booking on a dedicated fresh Kubernetes namespace rather than modifying existing Compose bookings.
**Evidence:** ps/logs and health response. Container packaging is not public authorization or storage HA.
**Restore:** python demo.py --stop retains volumes.

### TC-10 | Kubernetes services, probes and API replacement
**Objective:** demonstrate controller replacement and retained business state.
**Preconditions:** lab deployed, helper k defined; saved confirmed TC-01 booking.
**Test Data:** allocation-api deployment, original pod UID.
**Steps:**
```powershell
k get pods,pvc,services,jobs
k get endpointslices
k get deployment allocation-api -o yaml
k get pods -l app=allocation-api -o custom-columns=NAME:.metadata.name,UID:.metadata.uid
k delete pods -l app=allocation-api --wait=true
k rollout status deployment/allocation-api --timeout=180s
k get pods -l app=allocation-api -o custom-columns=NAME:.metadata.name,UID:.metadata.uid
```
1. Inspect printed probe configuration and eligible Service EndpointSlices.
2. After rollout, reload original booking; run invariants with --run TC-10.
**Expected Result:** new pod UID becomes Ready; original confirmed booking/seats survive. Brief API interruption is possible.
**Verification Method:** changed UID, rollout success, unchanged checkout and invariant PASS.
**Evidence:** before/after UIDs, probe YAML, endpoints, customer screenshot and invariant JSON.

**Scaling:** TC-16 explicitly runs 1/2/4 allocation-worker replicas against shared SQL state. Pod-prefixed request logs can prove participation. Configured/Ready replicas alone do not prove balanced work.

**Health limits:** APIs have startup/readiness/liveness probes; background workers have no progress probes. Normal deployment does not install HPA/metrics-server. TC-24 explicitly enables and observes optional lab autoscaling; configuration alone is not a scaling result.

<!-- pagebreak -->
## 8. Fault Tolerance and Recovery Testing
Use only the namespace-fixed k helper. Save evidence and reset lab before every independent scenario. Restore paused deployments even when a step fails. TC-11 to TC-17 are controlled outages; TC-21 adds a committed-reply loss and abrupt crash checkpoint.

### TC-11 | Payment worker pause
**Objective:** distinguish API availability, durable acceptance and recovered work.
**Preconditions:** fresh 300-second lab, sale open, active A/2 hold.
**Test Data:** original Request ID, Hold ID, seats and deadline.
**Steps:**
1. Stop the worker before payment:
```powershell
k scale deployment/payment-worker --replicas=0
k wait --for=delete pod -l app=payment-worker --timeout=90s
```
2. Complete mock payment once. Observe API and saved pending work:
```powershell
Invoke-RestMethod http://127.0.0.1:18100/api/payment/health
python experiments/run.py capture --case TC-11 --run TC-11 --phase paused
k exec deployment/payment-api -- python service.py monitor
```
3. Restore promptly:
```powershell
k scale deployment/payment-worker --replicas=1
k rollout status deployment/payment-worker --timeout=180s
python experiments/run.py capture --case TC-11 --run TC-11 --phase restored
```
**Expected Result:** API responds but no confirmation while paused; pending work survives. After return, same hold/seats confirm once without a renewed deadline.
**Verification Method:** pending monitor, final authoritative checkout and invariant PASS. If original TTL expired, honest expiry is required; mark confirmation variant inconclusive and repeat promptly.
**Evidence:** paused/restored captures, IDs/deadline screenshots and restoration/completion timestamps.
**Restore:** payment-worker=1 regardless of test outcome.

### TC-12 | Allocation worker pause
**Objective:** verify saved work resumes without re-registering.
**Preconditions:** fresh pre-sale lab.
**Test Data:** one B/2 registration.
**Steps:**
1. Pause the allocator:
```powershell
k scale deployment/allocation-worker --replicas=0
k wait --for=delete pod -l app=allocation-worker --timeout=90s
```
2. Register B/2 and start sale. Inspect queued Batches state and capture:
```powershell
python experiments/run.py capture --case TC-12 --run TC-12 --phase paused
```
3. Restore the consumer:
```powershell
k scale deployment/allocation-worker --replicas=1
k rollout status deployment/allocation-worker --timeout=180s
```
4. Observe original Request ID become RESERVED; pay before expiry, wait for confirmation, then capture:
```powershell
python experiments/run.py capture --case TC-12 --run TC-12 --phase restored
python experiments/run.py invariants --run TC-12
```
**Expected Result:** no allocator hold while paused; original saved job resumes and confirms once.
**Verification Method:** queued backlog before, same request after, one live hold and invariant PASS.
**Evidence:** captures, Batches/booking screenshots and worker logs.
**Restore:** allocation-worker=1. Process replacement without original work progressing is insufficient.

<!-- pagebreak -->
## 8. Fault Tolerance and Recovery (continued)
### TC-13 | Seat API dependency outage
**Objective:** verify pending payment is retained without false success.
**Preconditions:** fresh lab, open sale, active A/1 hold; enough original TTL for restoration.
**Test Data:** original request/hold, seat and deadline.
**Steps:**
1. Pause payment-worker as in TC-11; submit Complete mock payment.
2. Remove seat API, then restore payment-worker:
```powershell
k scale deployment/seat-api --replicas=0
k wait --for=delete pod -l app=seat-api --timeout=90s
k scale deployment/payment-worker --replicas=1
k rollout status deployment/payment-worker --timeout=180s
python experiments/run.py capture --case TC-13 --run TC-13 --phase outage
k exec deployment/payment-api -- python service.py monitor
```
3. Verify pending work, then restore:
```powershell
k scale deployment/seat-api --replicas=1
k rollout status deployment/seat-api --timeout=180s
python experiments/run.py capture --case TC-13 --run TC-13 --phase restored
python experiments/run.py invariants --run TC-13
```
**Expected Result:** dependency failure leaves pending/retrying work, not a false confirmation/new hold. Valid original hold eventually confirms after recovery; backoff means not instant. Checkout may return dependency unavailable during outage.
**Verification Method:** pending monitor and eventual refreshed backend confirmation with unchanged identity/deadline; invariant PASS.
**Evidence:** captures, payment-worker logs, timestamps.
**Restore:** seat-api=1 and payment-worker=1 even on failure.

### TC-17 | PostgreSQL/Redis pod replacement
**Objective:** verify PVC persistence, separately from continuous availability.
**Preconditions:** lab has a confirmed booking; no active holds/actions/writers.
**Test Data:** saved booking/queue and PVC UIDs.
**Steps:**
```powershell
python experiments/run.py capture --case TC-17 --run TC-17 --phase before
k delete pod postgres-0 redis-0 --wait=true
k rollout status statefulset/postgres --timeout=180s
k rollout status statefulset/redis --timeout=180s
python experiments/run.py capture --case TC-17 --run TC-17 --phase after
python experiments/run.py invariants --run TC-17
```
**Expected Result:** temporary API unavailability, then Ready stores; same saved records/PVC UIDs, new pod UIDs.
**Verification Method:** compare captures and original booking; create/confirm another party where capacity remains to check forward progress.
**Evidence:** captures, original/new booking screenshots and invariants. StatefulSets restore pods; investigate failed rollout before new writes. Cluster/disk deletion is outside this guarantee.

**Recovery behavior:** transient allocator failures remain durable with capped backoff rather than exhausting five retries. A lost original hold reply is reconciled by request identity, including an expired/cancelled original attempt, without issuing a new hold. Permanent conflicts still become BLOCKED and need investigation; there is no repair endpoint. TC-21/22 provide explicit fault injections. Storage HA, indefinite-outage availability and node failure are not claimed.

<!-- pagebreak -->
## 9. Performance and Scalability Testing
Keep machine, source/images, TTL/batch size and background workloads consistent. Run one workload at a time; reset before every trial; record failed/inconclusive runs. Use three repeats/configuration. No fixed latency or linear speedup is promised.

### TC-14 | Single-request baseline
**Objective:** measure client-to-frontend-to-seat HTTP time.
**Preconditions:** reset lab; one seat API/allocator worker; no other traffic.
**Test Data:** one C/1 request, one client thread; duration=actual completion.
**Steps:**
```powershell
python experiments/run.py contention --count 1 --workers 1 --run TC-14-r1
python experiments/metrics.py --run TC-14-r1
```
Reset and repeat with IDs TC-14-r2/r3.
**Expected Result:** one reservation, no UNKNOWN, no violations; actual timing populated.
**Verification Method:** metrics.json average/P95, elapsed time, HTTP rates; raw customer sample.
**Evidence:** per-run customers.json/csv, summary.json, metrics.json, before/after captures. With one sample average=P95; this is not a stable distribution or full booking latency.

### TC-15 | Concurrent scheduled registration
**Objective:** measure admission latency/rate and missing acknowledgements.
**Preconditions:** empty pre-sale lab before each run; do not start sale.
**Test Data:** 5 arrivals/s for 10 seconds, 50 arrivals, seed 42; up to 64 generator threads and 256 pending requests.
**Steps:**
```powershell
python experiments/run.py register --rate 5 --duration 10 --run TC-15-r1
python experiments/metrics.py --run TC-15-r1
```
Repeat r2/r3 after resets. Optional 20/s runs use separate IDs and the same duration. --profile spike is a different workload.
**Expected Result:** all offered registrations accepted/reconciled, no lost acknowledged IDs and no unknown, rejected or generator-dropped arrivals. PASS also requires maximum launch lag within one second; otherwise the trial is inconclusive.
**Verification Method:** reconcile offered, accepted, rejected, unknown and generator-dropped counts; inspect queue IDs.
**Evidence:** arrivals.json/csv, summary/metrics and captures.
**Duration:** ten seconds offered plus response drain; achieved_registration_rps includes drain. This measures admission, not confirmed bookings/s.

### Metric definitions
Average response time=mean recorded client HTTP durations; P95=linear interpolation over sorted measured durations. HTTP success rate=2xx/offered; error rate=non-2xx/transport failures divided by offered; missing samples/drops are separate. HTTP 200/no-fit is not booking success. Contention samples time the final attempt; total elapsed includes its retries.

Total workload time excludes image builds/reset. Booking goodput=confirmed customers/replay elapsed seconds. Decision wait=allocator decision timestamp minus queue eligibility; missing/negative timing is unavailable. Recovery time=authoritative completion minus component restoration timestamp; record both. Preserve all denominators and unsuccessful outcomes.

<!-- pagebreak -->
## 9. Performance and Scalability (continued)
### TC-16 | Compare 1, 2 and 4 allocation workers
**Objective:** measure equivalent workloads and inspect worker participation.
**Preconditions:** images loaded; lab can be reset; other replicas unchanged.
**Test Data:** F1 balanced trace, 40 parties, seed 42, batch size 10, TTL 120 seconds. Each trial runs both policies.
**Steps:**
```powershell
$scalingTrace = '.local/traces/scaling.json'
python experiments/run.py trace --scenario F1 --count 40 --seed 42 --output $scalingTrace
$comparisonArgs = @('--trace',$scalingTrace,'--reset-lab','--hold-ttl','120')
python experiments/run.py compare @comparisonArgs --replicas 1 --run TC-16-w1-r1
python experiments/run.py compare @comparisonArgs --replicas 2 --run TC-16-w2-r1
python experiments/run.py compare @comparisonArgs --replicas 4 --run TC-16-w4-r1
```
Repeat r2/r3, alternating worker-count order across repeats. Each command resets before each policy, configures workers and waits for rollout. Default replay timeout=420 seconds; measured completion time is saved. After EACH command, save participation logs if claiming multiple pods worked:
```powershell
k logs -l app=allocation-worker --all-containers=true --prefix=true --tail=200
```
**Expected Result:** matching initial inventory/batch boundaries, known terminal outcomes, correct policies and zero violations. More workers need not improve throughput: at most four sections allocate concurrently.
**Verification Method:** compare the SAME policy across worker counts using comparison.json and repeat-1-<policy>/summary.json; derive confirmed goodput from outcomes/elapsed_seconds. before/after captures show replicas/resources, not proof each pod worked.
**Evidence:** trace hash, raw customers, per-policy summaries, captures and prefixed request logs. Capturing logs after the final trial alone cannot prove earlier namespace participation.
**Restore:** Section 4 lab reset restores one replica and demand-cycle; restart B forward.

### TC-18 | Demand-Cycle versus FCFS
**Objective:** compare policy trade-offs with identical input/physical inventory.
**Preconditions:** TC-16; retain all pairs, including inconclusive.
**Test Data:** start with TC-16's one-worker pair. F2/F3 skew to small/large parties; F4 to section A; F5=80% occupied; F6=alternating gaps; F7=releases/later wave.
**Steps:** compare both policies within TC-16's one-worker comparison.json. To repeat with fragmented inventory, run:
```powershell
$fragmentTrace = '.local/traces/fragmented.json'
python experiments/run.py trace --scenario F6 --count 40 --seed 43 --output $fragmentTrace
$comparisonArgs = @('--trace',$fragmentTrace,'--reset-lab','--hold-ttl','120')
python experiments/run.py compare @comparisonArgs --replicas 1 --run TC-18-F6
```
**Expected Result:** matching fingerprints/boundaries and no violations; no automatic fairness-superiority claim.
**Verification Method:** compare per-section/party-size reservation and confirmation rates, sample sizes, median/P95 decision waits, overtakes and unknowns.
**Evidence:** trace.json, comparison.json, raw customers/inventory. Use at least ten independent seeds for research fairness claims; repetitions of one trace are not independent samples.

Fairness objective: equal opportunity for sizes 1-4 within each section. Summaries report the maximum-minus-minimum reservation-rate gap and Jain's index over those rates. Smaller gaps and indices nearer one indicate greater equality; zero service has no score. Missing groups or unknown outcomes prevent a full-size conclusion. Read these measures alongside waits, overtakes, utilization and sample sizes. Add --seeds 10 to compare to run independent consecutive seeds; paired differences are descriptive, not statistical significance.

<!-- pagebreak -->
## 9. Extended robustness experiments
These tests address the remaining professor questions. Reset lab before EACH independent command, preserve evidence, and use a new run ID. Full procedures and interpretation: experiments/ROBUSTNESS.md. Costs are excluded.

### TC-19 | Thousands of arrivals and mixed parties
**Steps:** after a fresh reset, run the surge and admission experiment:
```powershell
$surgeArgs = @('--rate','100','--duration','40','--profile','spike')
python experiments/run.py register @surgeArgs --admit --run TC-19-surge
```
**Expected Result:** about 2,100 offers across baseline/surge/recovery. Every offered arrival is accepted/reconciled, no acknowledged ID is missing, queue positions are unique 1..N and stable through admission, all admission outcomes resolve, SQL invariants remain safe. Generator drops, rejections or unknown outcomes prevent PASS. Arrival files distinguish scheduling delay from service latency.
**Evidence:** arrivals.json/csv, admission.json, before/after captures, summary.json. Compare baseline/surge P95 and actual throughput; this local generator does not prove arbitrary internet-scale capacity.
**Steps:** reset again, then run mixed-size contention:
```powershell
python experiments/run.py contention --count 40 --workers 32 --mixed --run TC-19-mixed
```
**Expected Result:** complete adjacent parties of sizes 1-4, no shared live ownership or partial party, at most ten C seats reserved, zero SQL violations. Winning mixture depends on scheduling. Evidence includes every request, party size and final inventory.

### TC-20 | Payment/cancellation/expiry race
**Steps:** fresh reset, run payment and cancellation together:
```powershell
python experiments/run.py race --run TC-20-active
```
Reset again with --hold-ttl 20, then:
```powershell
python experiments/run.py race --near-expiry --run TC-20-expiry
```
**Expected Result:** a consistent confirmed/cancelled/expired terminal winner, HTTP 200/202 or competing-operation 409, no duplicate successful payment or inconsistent seat ownership. A barrier starts the two HTTP calls together; network and worker scheduling determine the winner. Repeat several trials rather than requiring a particular winner.
**Evidence:** responses, authoritative checkout and database invariants in summary.json. Expiry housekeeping is real; no database deadline is rewritten.

<!-- pagebreak -->
## 9. Extended recovery, scaling and access
### TC-21/22 | Lost reply, abrupt crash and sustained outages
**Steps:** after a fresh five-minute lab reset before EACH command:
```powershell
python experiments/run.py fault --scenario lost-reply --run TC-21-reply
python experiments/run.py fault --scenario worker-crash --run TC-21-crash
python experiments/run.py fault --scenario redis --seconds 60 --run TC-22-redis
python experiments/run.py fault --scenario postgres --seconds 60 --run TC-22-sql
python experiments/run.py fault --scenario both --seconds 60 --run TC-22-both
```
**Expected Result:** the lab proxy commits a real seat hold then drops its reply. Crash mode SIGKILLs the allocator at that checkpoint. Recovery reuses the request, original hold and deadline; one hold history remains. Dependency mode preserves acknowledged registration across 60 seconds of storage unavailability, then allocates after restoration. No storage-availability promise is made during the outage.
**Evidence:** commit checkpoint, worker restart, hold history, outage samples and invariant checks. Tools restore dependency replicas/worker URLs in finally and remove the lab-only proxy. Inspect interrupted.json and restore components after forced host termination.

### TC-23 | Waiting-room API replicas
```powershell
$scaleArgs = @('--rate','50','--duration','30','--repeats','3')
python experiments/run.py scale-api --reset-lab @scaleArgs --run TC-23
```
**Expected Result:** clean 1/2/4-replica trials with identical offered traffic and seed, alternating order, no lost acknowledgements. Compare throughput, P95/errors and generator saturation; improvement is not assumed. served_by_instance records actual responding pod identities. This command resets lab before each trial and leaves main unchanged.

### TC-24 | Optional autoscaling
**Steps:** fresh reset; enable private Kind metrics/HPAs and apply sustained load:
```powershell
python experiments/run.py autoscale --install-metrics --run TC-24-config
python experiments/run.py register --rate 100 --duration 180 --profile spike --run TC-24-load
```
In another window, record timestamped k get hpa,pods and k top pods during load and for 180 seconds afterward. Use capture to save HPA state. Require observed scale-out and scale-in before claiming autoscaling. Configured 1-4 CPU HPAs target waiting-room/allocation workers; I/O-bound workers may not trigger. The local metrics-server uses a Kind-only kubelet TLS exception, not a production setting.
**Restore:** python experiments/run.py autoscale --disable --run TC-24-stop. Reset lab before manual scaling trials.

### TC-25 | Browser ownership and return
**Steps:** use a separate browser profile without admin access. Register a customer and record request/hold IDs, queue number and original deadline. Disconnect, refresh, close all tabs, reopen within seven days and select the saved customer. Check the same booking, including honest expiry after a long absence. A second profile must receive HTTP 403 for copied request/payment/cancellation IDs, sale opening and direct seat mutation. Administrator sign-in restores privileged demo controls; sign-out removes them.
**Evidence:** before/after identities, authoritative state, denied HTTP responses and no resulting mutation. Automated gateway and browser-access/recovery tests supplement this manual deployed procedure. Cookie deletion or a different browser does not provide account recovery.

<!-- pagebreak -->
## 9. Measurement records and verification status
### Resource observations and limits
During each workload, run periodically in another window and save timestamped output:
```powershell
python infra/k8s/kubectl.py -n csc3104-lab top pods
```
capture saves available resource metrics; missing metrics support no CPU/memory/HPA conclusion. Normal deployment does not install metrics-server. Compose docker stats --no-stream is a point sample, not a Kubernetes trial. Use logs/response instance IDs for participation and actual TC-24 observations for autoscaling conclusions.

### Empty results table: complete after execution
| Run / configuration | Time / average / P95 | Throughput / success / error | Safety / evidence |
|---|---|---|---|
| TC-14 baseline r1-r3 | Not measured | Not measured | Run folders |
| TC-15 5/s r1-r3 | Not measured | Not measured | Arrival records |
| TC-16 1 worker r1-r3 | Not measured | Not measured | Per-policy summaries |
| TC-16 2 workers r1-r3 | Not measured | Not measured | Per-policy summaries |
| TC-16 4 workers r1-r3 | Not measured | Not measured | Per-policy summaries |
| TC-11/12/13 recovery | Not measured | Pending/completed: not measured | IDs/timestamps |

### Actual execution in this revision: 12 November 2026
Source PASS: nine gateway, 24 allocator, 23 browser-recovery/two browser-access cases, and 61 seat-store/50 payment PostgreSQL tests. Other source checks are listed in the JSON capsule. Controlled-response tests remain distinct from deployed network checks.

Deployed PASS: 2,100 complete surge registrations/admissions with stable positions; 40 mixed parties; paired two-seed policies; one round of 1/2/4 API replicas; lost reply/runtime crash with expired-original-hold recovery; storage outages preserving confirmed/queued work; lifecycle races; gateway and normal booking acceptance. Live Chromium tab return restored original IDs, seats, queue number and deadline. Main confirmed ownership was preserved.

HPA expanded from one to four API pods. The 6,300-offer trial had 33 generator drops; scale-in was not captured. Workload/full cycle remain INCONCLUSIVE. Corrected attempts, scope and run IDs are in output/validation/robustness-results.md and robustness-implementation.json. No clean-machine, full ten-seed, full cross-browser or production-security claim follows.

### Historical evidence: separate from this revision
experiments/VALIDATION.md records bounded 10 November checks; output/validation/ contains their acceptance-summary.json, research-smoke-summary.json and FCFS_pair_smoke.json. These are historical, not current-source acceptance or statistical scaling/fairness evidence. Export ignored raw runs separately when required.

### Optional automated deployed acceptance
After normal image build/load and with csc3104-check absent:
```powershell
python experiments/acceptance.py
```
This implemented harness runs booking/policy/recovery/storage checks in its own disposable namespace and removes it afterwards. Save stdout and .local/test-results/acceptance-* folders. Main/lab are preserved. It was not rerun here.

<!-- pagebreak -->
## 10. Testing Summary Matrix
Expected results are acceptance conditions; enter observed results in your own evidence log.

| Test ID | Test Case | Concept Demonstrated | Expected Result | Verification Method |
|---|---|---|---|---|
| TC-01 | Register/pay | Service composition | Same adjacent party confirmed | IDs, seats, invariants |
| TC-02 | Decline/retry | Idempotency/deadline | Same hold, no extension | Checkout comparison |
| TC-03 | Cancel | Atomic release | Whole party released | Seats/checkout |
| TC-04 | Expire/late pay | Housekeeping | Released; late HTTP 409 | Backend/checker |
| TC-05 | Capacity/tabs | Whole party/reconnect | No partial; stable IDs | Outcomes/invariants |
| TC-06 | Invalid input | API validation | HTTP 400/404; no mutation | Script assertions |
| TC-07 | Service trace | Async durable work | Correlated jobs complete | Captures/logs |
| TC-08 | Contention | Concurrency/consistency | 10 holds/10 no-fit; safe | Raw outcomes/SQL |
| TC-09 | Containers | Docker/networking | Running apps/init exit 0 | ps/logs/health |
| TC-10 | API replacement | Kubernetes/probes | New pod; same booking | UIDs/rollout |
| TC-11 | Payment pause | Durable recovery | Pending then same hold | Monitor/IDs |
| TC-12 | Allocator pause | Saved queue | Same request resumes | Backlog/outcome |
| TC-13 | Seat outage | Retry/reconciliation | No false success; resumes | Monitor/invariants |
| TC-14 | Baseline | Latency | Safe measured call | metrics/raw sample |
| TC-15 | Scheduled arrivals | Concurrent admission | No lost acknowledged IDs | Arrival reconciliation |
| TC-16 | 1/2/4 workers | Manual scaling | Equivalent safe work | Timing/replicas/logs |
| TC-17 | Store replacement | Persistence | Same records/PVCs | Captures/new booking |
| TC-18 | Policy comparison | Controlled evaluation | Same inputs; all outcomes | Hashes/group metrics |
| TC-19 | Surge/mixed parties | Admission/concurrency | Stable IDs/positions; whole parties | Arrivals/SQL |
| TC-20 | Lifecycle race | Atomic transitions | One consistent terminal outcome | Checkout/SQL |
| TC-21 | Crash/lost reply | Idempotent recovery | Original hold/deadline retained | Checkpoint/history |
| TC-22 | Storage outage | Durable queued work | Preserved booking/job; recovery | Samples/SQL |
| TC-23 | API replicas | Horizontal scaling | Complete comparable trials | Instance IDs/latency |
| TC-24 | Optional HPA | Automatic scaling | Observed scale-out/in and health | Metrics/HPA/events |
| TC-25 | Browser ownership | Access/session recovery | Own booking restored; cross-user denied | Cookies/HTTP/state |

### Result record template
Record Test ID; run ID; source revision/changes; date/time; machine limits; policy/replicas/batch/TTL; input trace hash; exact actions; observed terminal counts/status; measured values; evidence filenames; expected-versus-observed differences; restoration completed. Retain run.json and before/after captures when generated. Use new run IDs instead of overwriting failing evidence.

Scope limits: verified personal accounts, HA storage, node failover, cloud-node scaling, cost analysis and exactly-once transport are not claimed. Optional features require recorded execution.

<!-- pagebreak -->
## 11. Troubleshooting and Cleanup
| Symptom | Check / corrective action |
|---|---|
| Docker pipe missing | Start Docker Desktop/Linux engine; docker version and prerequisite check. Do not reset storage. |
| Port conflict | Get-NetTCPConnection -LocalPort 18100 -ErrorAction SilentlyContinue. Stop your old forward only. Compose supports python demo.py --port 18082; this lab guide assumes 18100. |
| Main shown instead of lab | Read /api/demo/context; require csc3104-lab. Restart B's correct forward. |
| ImagePullBackOff/stale UI | python demo.py --kubernetes rebuilds/loads images; then redeploy lab. No concurrent deployments. |
| Pending pod/failed init | k get pods,events; k describe pod <actual-name>; logs of listed failed Job/pod; check PVC/resource status. |
| DB/password error | Keep generated credentials with initialized PVCs. Changing a file does not rotate DB passwords. Inspect references without sharing Secrets. |
| Queue/checkout unavailable | Inspect waiting-room, allocation-api, seat-api, payment-api logs. HTTP 502/503 is not no-fit; retry same identity/action. |
| Healthy API/stuck worker | Inspect worker logs, pending/blocked backlog, original expiry and payment monitor. |
| Allocator BLOCKED | Preserve evidence/errors. No repair endpoint; do not delete rows or invent no-seat to advance batches. |
| Old customer after reset | Restart forwarding, reload, My booking > New user; backend records were intentionally reset. |

### Logs and evidence
In Window A with k from Section 4:
```powershell
k get pods,events
k logs deployment/waiting-room --tail=100
k logs deployment/allocation-worker --tail=100
k logs deployment/payment-worker --tail=100
k exec deployment/payment-api -- python service.py monitor
```
For a restarted container, k logs <actual-pod-name> --previous may expose prior logs. Copy run folders from .local/test-results after checking for sensitive operational data; exclude generated Secrets, .env.core and kubeconfig. Captures avoid exporting Secrets.

### Restore and stop
Restore each paused deployment to its original count, normally one, and wait for rollout. Stop B's forward with Ctrl+C. To stop lab while preserving its PVCs/credentials:
```powershell
k scale deployment --all --replicas=0
k scale statefulset --all --replicas=0
```
To stop main Kubernetes and/or Compose:
```powershell
python demo.py --kubernetes --stop
python demo.py --stop
```
Resume main with its normal startup; resume lab with python experiments/run.py lab without --reset-lab and restart forwarding. To return the disposable lab to initial empty state, save evidence then repeat Section 4's --reset-lab. Do not delete main namespace/volumes/PVCs or Kind cluster as routine cleanup; cluster deletion loses node-local storage. Verification harnesses remove their own csc3104-check; inspect leftovers before rerunning.

**Supporting scripts:** experiments/run.py, runtime.py, workloads.py, metrics.py, invariants.sql; tests/docker_booking_smoke.py and http_validation_smoke.py. Editable source: output/pdf/GROUP02_INSTRUCTIONS.md; renderer: experiments/build_instructions.py (requires reportlab).

