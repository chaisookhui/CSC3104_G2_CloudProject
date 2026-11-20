# Fair Seat Allocation
CSC3104 Cloud and Distributed Computing | Group 02

**Testing Instructions**

## 1. Introduction
This application allocates adjacent seats to parties of one to four people. Customers register for a sale, receive a queue position when the sale opens, and receive a whole-party reservation if a suitable block exists. A mock payment confirms the reservation. Unpaid reservations expire; customers can cancel an unpaid reservation. No money or real payment details are involved.

This document lets an examiner deploy the submitted source, test the implementation and retain evidence. Test procedures belong in this PDF and the CLI. The application provides Overview, Batches, Seat map and My booking for observing actual behavior, without displaying a test-case checklist.

**Implemented:** separate HTTP services; Redis atomic admission; PostgreSQL transactions and locks; fixed-batch scheduling; durable asynchronous allocation/payment jobs; leases and fenced acknowledgements; specific idempotent operations; retryable callbacks/outboxes; container orchestration; manual horizontal scaling; persistent local storage.

**Limits:** one inventory; single-node Kind cluster; no complete waitlist/rejoin workflow, consensus, cross-service atomic transaction or storage HA. The gateway enforces browser ownership and administrator access when its generated service credential is configured. This is a browser session, not a verified account or cross-device login. Keep access on localhost. Optional lab HPAs and fairness/scaling benefits require measured evidence; cost analysis is excluded.

### Reading map
1. Sections 1.1-1.2: launch quickly and choose a demonstration; Sections 3-4: full setup and isolated lab.
2. TC-01 to TC-06: customer journeys and invalid input.
3. TC-07/08: service communication and concurrent seat safety.
4. TC-09/10 and TC-11/12/13/17: containers, orchestration and recovery.
5. TC-14/15/16/18: measured baseline, load, scaling and policy comparisons.
6. TC-19 to TC-25: surge, lifecycle races, injected faults, API scaling, separate HPA cycles and browser ownership.
7. Sections 9.7-9.9: saved results, provenance and evidence; Sections 10-10.1: expected versus recorded results; Section 11: troubleshooting and safe stopping.

**Evidence labels:** Implemented means inspected in source. Expected is an acceptance condition, not a result. PASS requires execution and evidence. NOT RUN, BLOCKED, FAIL and INCONCLUSIVE remain distinct. No hold history means an inconclusive safety check, not a booking pass.

**Final validation scope:** all 25 documented cases passed their recorded local acceptance conditions. TC-01 to TC-13, TC-17 and TC-25 have new final-version functional/browser/deployment evidence. TC-14/15/16/18/19/20/21/22/23/24 use the complete final v9 cohorts, independently re-audited with unchanged application sources and matching captured image IDs. This is the same evidence and scope as the updated results report. It is not a guarantee on another machine. This document correction generated no new application test results.


**Source basis:** service implementations, schemas/migrations, Dockerfiles, deployment configurations, launcher, frontend, tests and experiment tools in this checkout. The local four-page project assignment brief was reviewed. It requires containers and/or Kubernetes, tested advertised functionality and explicit testing instructions. This document is the testing guide, separate from the research article.

<!-- pagebreak -->
## 1.1 Quick Start - Running and Testing the Application
### A. Before you start
Use Windows x64 PowerShell in the extracted repository folder (containing demo.py), Python 3.10+ and running Docker Desktop with Linux containers. Allow at least 2 CPUs and 4 GiB Docker RAM; 8 GiB is recommended. First startup needs internet and several minutes. Full checks, ports and load-test resources: Section 3.

### B. Open the main application
Run one startup option, then open its address in a browser. Kubernetes:
```powershell
python demo.py --kubernetes
```
Main Kubernetes: http://127.0.0.1:18090. Alternatively, Docker Compose:
```powershell
python demo.py
```
Compose: http://127.0.0.1:18080. Existing bookings are retained. This opens the main application; no lab reset is required. For retained older dispatcher storage, read Section 11.1 before upgrading.

### C. Demonstrate a booking
1. Open the address for your chosen startup option. Use a fresh pre-sale inventory for the TC-01 acceptance test; see Section 4 for the isolated lab.
2. Retrieve the local password with python experiments/access.py --namespace csc3104 (Kubernetes) or python experiments/access.py --compose. Choose Administrator sign in > enter password > Sign in. This is local administrator access, not customer account registration.
3. Open My booking > New user; enter a fictional name such as Alice Test > Continue.
4. Choose Section A and Party size 2 > Register once. Record the User ID and Request ID.
5. In Overview, choose Start sale once. If already open, do not restart it; use a fresh lab for the exact pre-sale TC-01 procedure.
6. Return to My booking. Wait for RESERVED / Seats reserved; check two adjacent seats and the Pay before deadline.
7. Choose Pay before that deadline. This simulates payment; no card details or money are required. Wait for CONFIRMED.
8. Check Seat map, then reload My booking. The confirmed seats and original booking identity should remain. Full TC-01 checks are in Section 5.

### D. Use the isolated test lab
Main Kubernetes uses csc3104; experiments use separate csc3104-lab at http://127.0.0.1:18100. Build/load images with the Kubernetes startup first, then follow Section 4 for lab creation, its separate port-forward window and administrator password.
**WARNING - DELETES LAB DATA:** python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10 deletes existing isolated lab bookings, queue, PVCs and credentials. Preserve lab evidence first. It is not needed merely to open main. Never reset main storage for these tests.

### E. View evidence or run a new test
This PDF explains **how to test**. GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf summarises **what was observed and what it means**. The supporting raw evidence contains the individual request measurements, logs, screenshots and database checks used to verify those summaries; audits assess the saved records.

Most raw evidence is supplied in the attached GROUP02_Submission.zip on the [submission release page](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest), rather than the branch file listing. Extract it once and open CSC3104_G2_CloudProject/START_HERE.md. Section 9.9 maps the evidence folders inside that extracted project.

Sections 5-9.6 contain all 25 procedures; Section 1.2 suggests demonstrations. Sections 9.7-9.9 locate the recorded 25/25 local PASS results, final report and exported raw evidence in output/review-package/. Reading saved evidence generates no traffic. A new execution needs fresh observations and a new run ID; its result is not pre-filled PASS.

<!-- pagebreak -->
## 1.2 Recommended Examiner Demonstration Route
These five demonstrations highlight the distributed mechanisms. They do not replace the complete 25-case suite. Read each detailed precondition, save evidence, restore components and prepare the required fresh lab between independent tests. Do not run them against one unchanged lab state.

| Test / method | What it demonstrates | Detailed instructions |
|---|---|---|
| TC-01 / Mixed | Normal booking, adjacent seats, mock payment and original identity after reload. | Section 5, TC-01; manual UI actions plus automated SQL invariants. |
| TC-08 / Automated | Concurrent hold requests and double-booking prevention. | Section 6, TC-08; contention driver, exact outcome counts and SQL checks. |
| TC-10 / Mixed | Kubernetes allocation API pod replacement and booking recovery. | Section 7, TC-10; manual deletion/inspection and browser reload. |
| TC-21 / Automated | Recovery after a lost committed reply or abrupt worker crash. | Section 9.4, TC-21/22; run the lost-reply and crash commands separately. |
| TC-24 / Automated | Actual API/worker scale-out, scale-in and repeated scale-out. | Section 9.5, TC-24; full phase, CPU, backlog and safety criteria. |

### Saved evidence and effect of reproduction
All five have saved passing evidence. Viewing those files changes no deployment. Extract GROUP02_Submission.zip and open its CSC3104_G2_CloudProject folder first. The .local/test-results/ and output/validation/ evidence paths below are included in that submission folder; full case selection is in Section 9.8. Paths created by a fresh manual rerun are separate from these recorded runs.

| Test | Saved evidence available | Changes when reproduced |
|---|---|---|
| TC-01 | Yes: all25-audit.json: TC-01 evidence; screenshots and IDs. | Creates a lab booking. Prepare clean five-minute pre-sale lab; reset deletes old lab data. |
| TC-08 | Yes: all25-audit.json: TC-08 evidence. | Reset to ten fresh Section C seats first; creates contested lab holds. |
| TC-10 | Yes: all25-audit.json: TC-10 evidence. | Requires a confirmed lab booking; deletes allocation API pod, preserving stored booking data. |
| TC-21 | Yes: tc-fix-regression-v9 and its TC21 child runs. | Each fault run needs fresh lab setup; resets lab and injects reply loss/worker termination. |
| TC-24 | Yes: tc-fix-24-api-v9 and tc-fix-24-worker-v9. | Each study resets lab, creates HPA/load and changes replicas; restore after each target. |

**TC-24 is lengthy:** each target requires at least 18.5 minutes of measured phases, plus deployment, admission and evidence collection. API and worker studies run sequentially. For review without reproduction, inspect timeline.json/jsonl, phases.json, summary.json, HPA/pod/CPU/backlog samples and report-v9/tc24-*.png/.svg (Section 9.9). Saved-timeline inspection is not a newly executed HPA test.

### Navigation and recording
To locate a saved run, open output/validation/all25/all25-audit.json and use the named case's evidence field as its actual folder path.

The PDF bookmarks follow the numbered headings. Section 10 gives concepts and expected outcomes; its companion Section 10.1 gives methods and the recorded result. Section 11 distinguishes inspection, component restart, storage-preserving stop and destructive lab reset. Retain your own observed result and evidence for every newly executed case.

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
| Host Python 3.10+ | python --version. Launchers use standard libraries; scheduled load tools additionally require experiments/requirements-load.txt. App packages run inside images. |
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

Install the pinned host load-generator dependency before TC-15/19/23/24 (use the same Python interpreter for installation and commands):
```powershell
python -m pip install -r experiments/requirements-load.txt
```
This installs aiohttp 3.13.3. Use a virtual environment if the host Python installation is managed. Optional graph generation separately requires matplotlib; graph creation is not an acceptance test.

### Configuration and datasets
No manual credentials are needed for local startup. Compose generates ignored .env.core. Kubernetes generates .local/k8s/secrets-<namespace>.json and a Secret. Retain credentials with initialized storage. Do not copy another machine's .local directory or publish Secrets/kubeconfig. Editing a password file alone does not rotate the database password.

Relevant settings: HOLD_TTL_SECONDS=300, BATCH_SIZE=50 in main/10 in this lab, ALLOCATION_POLICY=demand-cycle or lab fcfs, WAITING_ROOM_STORAGE=redis, REDIS_URL, QUEUE_KEY, DATABASE_URL, ALLOCATION_DATABASE_URL, DISPATCHER_DATABASE_URL, PAYMENT_DATABASE_URL, PAYMENT_API_TOKEN and service URLs. See core.env.example and infra/k8s/local/config.yaml; launchers supply credentials and internal DNS addresses.

Development inventory: A=30, B=20, C=10, D=10, ten seats per row. Manual tests use fictional names; no upload required. F1-F7 traces are generated by documented commands with saved seeds.

**Runtime distinction:** Dockerfiles specify frontend Python 3.11, waiting room 3.12 and seat/allocation/dispatcher/payment 3.15.0. Host Python runs launchers. Native service development has separate setup.ps1/pinned dependency requirements and is unnecessary for the recommended container route.

<!-- pagebreak -->
## 4. Installation and Deployment
### A. Start the main system
For an existing installation with retained dispatcher data, read the upgrade rule in Section 11 before deploying new images. The lab studies below always use fresh isolated storage.
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
## 5.1 Functional Testing (continued)
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
## 8.1 Fault Tolerance and Recovery (continued)
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

### TC-14 | Extended direct seat-store baseline
The three original single-request trials in Section 9 retain their original procedure and acceptance evidence. This extended study measures the local `POST /seats/hold` HTTP path through a loopback port-forward to `seat-api`. End-to-end booking includes browser and frontend activity, waiting-room admission, batching, allocation, and payment through confirmation.

**Set up and run**

Start Docker with Linux containers and use the project Kind cluster with its images loaded. Use host Python 3.10 or later and install Matplotlib 3.8 or later for the exporter. Run from the repository root. Use a new run ID and export directory for each cohort. Allow about 5-10 minutes for the full run.

```powershell
python experiments/tc14_extended.py --run tc14-extended-repro01
python experiments/tc14_report.py --run tc14-extended-repro01 --output output/tc14-repro01
```

The collector creates a fresh disposable namespace per trial with one Ready pod per component, a 300-second hold TTL and batch size 10. Each trial starts with 200 available Section C seats. Ten sequential one-seat warm-up holds precede the 100 measured requests. There is one client request in flight at a time and each attempt uses a new TCP connection and a unique request ID. Run without concurrent benchmarks or changes to the cluster.

**Verify and save evidence**

1. Check that all five trials attempted 100 measured requests each. Confirm the summary reports 500 successful holds, zero failed or missing requests, and zero SQL invariant violations for a passing cohort. The trial evidence includes deployment settings, inventory snapshots and SQL audit results.
2. Save `raw-observations.csv` and `raw-observations.json`. Keep warm-up rows and every unsuccessful attempt. Summarize latency from successful measured holds only. Keep `summary.csv`, `summary.json` and both charts.
3. Inspect trial variation alongside the pooled estimate. Record any failed or incomplete trial with its observed outcomes. There is no fixed latency target for this baseline.

The recorded run `tc14-extended-20261119` passed all five trials. Its 500 measured holds had a 26.51 ms median, 63.43 ms P95 and 91.67 ms P99, with zero SQL invariant violations. See the TC-14 extended study in the results report, `docs/TC14_EXTENDED_RESULTS.md` and `output/tc14-extended-20261119/` for the methodology, data and figures.

<!-- pagebreak -->
### TC-15 | Concurrent scheduled registration
**Objective:** measure admission latency/rate and missing acknowledgements.
**Preconditions:** empty pre-sale lab before each run; do not start sale.
**Test Data:** 5 arrivals/s for 10 seconds, 50 arrivals, seed 42; shared asynchronous open-loop generator, 4,096 connection capacity, 15-second request timeout, no client submission retries.
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

Scheduled launch is measured at aiohttp's headers-send callback after connection acquisition. Maximum launch lag must be <=1 second. Client/session preparation is recorded separately before the offered-arrival epoch; no HTTP connection is warmed up. Connection delays and runtime stalls after that epoch still count. Gateway upstream attempts are recorded separately from client HTTP success; successful HTTP alone does not prove there was no internal retry.

<!-- pagebreak -->
## 9.1 Worker Scaling Procedure
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

<!-- pagebreak -->
## 9.2 Policy Comparison Procedure
### TC-18 | Demand-Cycle versus FCFS
**Objective:** compare policy trade-offs with identical input/physical inventory.
**Preconditions:** TC-16; retain all pairs, including inconclusive.
**Test Data:** start with TC-16's one-worker pair. F2/F3 skew to small/large parties; F4 to section A; F5=80% occupied; F6=alternating gaps; F7=releases/later wave.
**Steps:** compare both policies within TC-16's one-worker comparison.json. For the independent ten-seed F1 cohort used in the final validation:
```powershell
$fairTrace = '.local/traces/scaling.json'
$fairArgs = @('--trace',$fairTrace,'--reset-lab','--hold-ttl','120')
python experiments/run.py compare @fairArgs --replicas 1 --seeds 10 --run TC-18-F1
```
Generate scaling.json with the TC-16 F1 seed-42 trace command first. This runs seeds 42-51 with both policies. Optional additional fragmented-inventory exploration (not part of the final F1 validation cohort):
```powershell
$fragmentTrace = '.local/traces/fragmented.json'
python experiments/run.py trace --scenario F6 --count 40 --seed 43 --output $fragmentTrace
$comparisonArgs = @('--trace',$fragmentTrace,'--reset-lab','--hold-ttl','120')
python experiments/run.py compare @comparisonArgs --replicas 1 --run TC-18-F6
```
**Expected Result:** matching fingerprints/boundaries and no violations; no automatic fairness-superiority claim.
**Verification Method:** compare per-section/party-size reservation and confirmation rates, sample sizes, median/P95 decision waits, overtakes and unknowns.
**Evidence:** trace.json, comparison.json, raw customers/inventory. Use at least ten independent seeds for research fairness claims; repetitions of one trace are not independent samples.

**How to interpret a PASS:** Passing TC-18 confirms that the scheduling policies completed the controlled comparison and satisfied the defined correctness requirements. It does not by itself establish that Demand-Cycle provides superior fairness, latency, throughput or seat utilisation.

Read trade-offs together: number of booking groups served; reservation success by party size; seat utilisation; queue overtakes; waiting time; and Jain's fairness index. The recorded ten-seed F1 evidence suggests Demand-Cycle serves more booking groups on average, while FCFS has a higher party-size fairness index. Sources: tc-fix-regression-v9-TC18/comparison.json and the reviewer graphs' tc18-policy-seeds.csv / tc18-section-fairness.csv. These are descriptive observations, not universal superiority or statistical significance.

Fairness objective: equal opportunity for sizes 1-4 within each section. Summaries report the maximum-minus-minimum reservation-rate gap and Jain's index over those rates. Smaller gaps and indices nearer one indicate greater equality; zero service has no score. Missing groups or unknown outcomes prevent a full-size conclusion. Read these measures alongside waits, overtakes, utilization and sample sizes. Add --seeds 10 to compare to run independent consecutive seeds; paired differences are descriptive, not statistical significance.

### TC-18 | Follow-up scheduler findings

| Study | Completed evidence | Observed result |
|---|---|---|
| TC-18 F2/F3/F6 | 30 matched seed pairs; 60 policy replays | All correctness checks passed. Mean DC-FCFS party/Jain deltas: F2 -0.1/+0.009405; F3 +0.5/+0.028361; F6 0/0. |

The original F1 parties-versus-Jain trade-off did not recur on mean paired effects. F3 nevertheless had a worse rate gap despite higher Jain. Missing sizes remain missing; Jain requires all four sizes, known outcomes and positive service. F6 fixture bookings are excluded.

<!-- pagebreak -->
## 9.3 Extended Robustness Experiments
These tests address the remaining professor questions. Reset lab before EACH independent command, preserve evidence, and use a new run ID. Full procedures and interpretation: experiments/STUDY_PROTOCOLS.md#robustness. Costs are excluded.

### TC-19 | Thousands of arrivals and mixed parties
**Steps:** use the existing study wrapper to reset before each trial, run all three original surges, then run the mixed-party test on a separate fresh lab:
```powershell
python experiments/study.py --case 19 --reset-lab --run TC19-exam
```
**Test Data:** each surge is exactly 2,100 offers: 5/s for 10 seconds, 100/s for 20 seconds, 5/s for 10 seconds. Three fresh repetitions; original 600-second admission deadline and one-second maximum launch lag. Mixed test: 40 parties, sizes 1-4, 32 concurrent clients, ten Section C seats.
**Expected Result:** every offered arrival accepted/reconciled, no missing acknowledged ID, unique positions 1..N stable through admission, all outcomes RESERVED or UNAVAILABLE within 600 seconds, zero SQL violations. Generator drops, rejections, HTTP failures, unresolved outcomes or excess launch lag prevent PASS. UNAVAILABLE means valid inventory exhaustion, not a confirmed booking.
**Expected Result:** mixed outcomes contain complete adjacent parties, no shared live ownership or partial party, at most ten C seats reserved and zero SQL violations. Winning mixture depends on scheduling.
**Evidence:** .local/test-results/TC19-exam/ contains surge-1/2/3 and mixed, raw arrivals/customers, admission records, preflight, captures, metrics/timeline and summary.json. Preserve every failed/inconclusive attempt. These registration/allocation workloads do not perform payment.

### TC-19 | Follow-up burst findings

| Study | Completed evidence | Observed result |
|---|---|---|
| TC-19 bursts | Three trials per peak 100/150/200 per second | All nine passed; all 27,900 offers accepted. Maximum admission 178.1/269.7/352.0s, within 600s. |

Burst success means terminal processing, including unavailable/expired parties, not thousands of booked seats.

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
## 9.4 Recovery, Scaling and Access
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
python experiments/study.py --case 23 --reset-lab --run TC23-exam
```
**Test Data:** 50 arrivals/s for 30 seconds = 1,500 offers per trial; 1/2/4 API replicas, three repetitions each, alternating order. Each trial resets lab, removes HPAs, verifies exact Ready replicas, Redis and all four SQL databases, and records responding pod IDs.
**Expected Result:** all offers accepted/reconciled, zero HTTP failures/drops, maximum launch lag <=1 second, no missing/duplicate IDs, zero SQL violations and every requested replica actually serving. Compare P95/throughput/resources; more replicas need not improve performance. Existing workloads and assertions are retained.
**Evidence:** .local/test-results/TC23-exam/ holds nine trials and their raw response instance IDs, configuration/source hashes, arrivals, CPU/RAM samples and cohort summary.

Optional capacity study, separate from fixed-load acceptance:
```powershell
python experiments/study.py --case capacity --reset-lab --run TC23-cap-exam
```
This runs 20/40/60/80/100 arrivals/s for 30 seconds at each 1/2/4 setting, one trial per point. In addition to correctness/delivery checks, sustainable means P95 <=1,000 ms and accepted throughput >=95% of offered rate. The saved final study also tested 200/s separately. Highest passing tested rate is a lower bound, not the true maximum; single capacity points have no confidence interval.

<!-- pagebreak -->
## 9.5 Automatic Scaling Procedure
### TC-24 | Optional autoscaling
**Preconditions:** current application images built/loaded, pinned host load dependency installed, enough free resources, no concurrent experiments. Each target needs at least 18.5 minutes of measured phases plus deployment, admission and evidence collection. Run targets sequentially.
**Steps:** if Metrics Server is absent, install it and remove the setup HPAs before measurement:
```powershell
python experiments/run.py autoscale --install-metrics --run TC-24-config
python experiments/run.py autoscale --disable --run TC-24-config-clean
```
With a working Metrics Server, skip those two setup commands. Run each isolated target:
```powershell
python experiments/study.py --case 24-api --reset-lab --run TC24-api-exam
python experiments/study.py --case 24-worker --reset-lab --run TC24-worker-exam
```
The wrapper resets only csc3104-lab before each target, captures baseline configuration, attaches only that target's HPA and records actual pod/CPU/backlog evidence throughout. It retains the original offered profile and admission/safety checks. Main is unchanged by these study commands. Manual scaling after HPA attachment invalidates the automatic-scaling claim.

| Phase | Duration | API target | Worker target |
|---|---|---|---|
| Low baseline | 120 s | 2/s = 240 offers | 1/s = 120 offers |
| Original spike | 180 s | 5/s x45s, 100/s x90s, 5/s x45s | Same 9,450 offers |
| Recovery | 600 s | Zero new offers | Zero new offers; backlog must drain |
| Repeated spike | 180 s | Identical 9,450 offers | Identical 9,450 offers |
| Final observation | 30 s | Continue evidence collection | Continue evidence collection |

**Configuration:** min 1/max 4 replicas, 50% CPU target, 60-second downscale stabilization; scale up at most one pod/30s and down one/60s. API request=50m, limit=500m. Worker request=200m, limit=500m; the measured idle floor informed this lab calibration. For the worker-only cycle, waiting-room API is fixed at four Ready replicas BEFORE measurement/HPA attachment; only the worker autosizes. API traffic remains pre-sale; worker traffic opens the sale and creates genuine allocation work. No synthetic CPU workload is used.

**Expected Result:** actual Ready replicas follow 1 -> more than 1 -> 1 -> more than 1 in phase order; CPU is above target under high load and below at recovery end. All 19,140 API offers / 19,020 worker offers must be delivered, maximum launch lag <=1 second, no missing/duplicate IDs and zero SQL violations. Worker backlog must drain and one Ready worker must be observed within the original 600-second recovery window. Preserve actual offer-end timestamps as well as phase timestamps.
**Verification Method:** raw timeline/pod/CPU/backlog samples and final summary; a desired replica count or HPA manifest alone is insufficient. Deleting an HPA during cleanup does not count as automatic scale-in. A late diagnostic drain cannot turn a missed 600-second criterion into PASS. Missing data or unmet timing remains FAIL/INCONCLUSIVE as appropriate.
**Evidence:** .local/test-results/TC24-api-exam/ and TC24-worker-exam/, including raw phase arrivals, configuration/preflight, timeline.jsonl, HPA/pod/events/logs, SQL/admission checks and summary.json. Metrics Server samples have cached windows; missing CPU is not zero. Kind-only kubelet TLS exception is not a production configuration.
**Restore:** the wrapper removes its HPA in cleanup. Save evidence, then restore the ordinary lab and restart any manual forward:
```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

### TC-24 | Follow-up HPA findings

| Study | Completed evidence | Observed result |
|---|---|---|
| TC-24 CPU HPA | Two full cycles per target | All four passed scale-out, original 600s recovery and repeated scale-out. API held at four Ready replicas in worker-only tests. |

<!-- pagebreak -->
## 9.6 Browser Access and Evidence Collection
### TC-25 | Browser ownership and return
**Steps:** use a separate browser profile without admin access. Register a customer and record request/hold IDs, queue number and original deadline. Disconnect, refresh, close all tabs, reopen within seven days and select the saved customer. Check the same booking, including honest expiry after a long absence. A second profile must receive HTTP 403 for copied request/payment/cancellation IDs, sale opening and direct seat mutation. Administrator sign-in restores privileged demo controls; sign-out removes them.
**Evidence:** before/after identities, authoritative state, denied HTTP responses and no resulting mutation. Automated gateway and browser-access/recovery tests supplement this manual deployed procedure. Cookie deletion or a different browser does not provide account recovery.

### Resource observations and limits
During each workload, run periodically in another window and save timestamped output:
```powershell
python infra/k8s/kubectl.py -n csc3104-lab top pods
```
capture saves available resource metrics; missing metrics support no CPU/memory/HPA conclusion. Normal deployment does not install metrics-server. The study wrappers automatically collect timestamped evidence. Compose docker stats --no-stream is a point sample, not a Kubernetes trial. Use logs/response instance IDs for participation.

### Evidence handling
Run one workload at a time; use a fresh run ID and preserve failures alongside passes. Export .local/test-results/<run-id>/ before resetting. Keep original rates, counts, TTLs, deadlines and safety assertions. Do not overwrite a failed or incomplete run to obtain a PASS. Interrupted.json and partial timelines are diagnostic evidence, not completed acceptance.

Full build/upgrade, exact measurement methods, interruption/resume rules and saved-data graph generation are documented in experiments/STUDY_PROTOCOLS.md#scaling. No trial is run by opening or rebuilding this PDF. Examiner observations must be recorded separately from the saved results on the following page.

Scope limits: verified personal accounts, HA storage, node failover, cloud-node scaling, cost analysis and exactly-once transport are not claimed. Optional features require recorded execution.

### Optional automated deployed acceptance
After normal image build/load and with csc3104-check absent:
```powershell
python experiments/acceptance.py
```
This optional harness runs booking/policy/recovery/storage checks in its own disposable namespace and removes it afterwards. Save stdout and .local/test-results/acceptance-* folders. The final 15-case coverage completion used experiments/examiner_verify.py and its real Chromium UI/HTTP/database checks, rather than rerunning this optional bounded harness. TC-14/15/16/18/19/20/21/22/23/24 retain their full v9 workloads. See experiments/README.md#examiner-verification for the exact verification/audit workflow. No application tests were launched for this document correction.

<!-- pagebreak -->
## 9.7 Saved Validation Results
These are actual saved local results for the final application images, not predictions for another machine. The complete 25-case results are in output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf and output/validation/all25/all25-audit.json. Performance/fault detail remains in output/validation/tc-fixes/FINAL_REPORT.md.

| Case / cohort | Actual result | Measurements and limits |
|---|---|---|
| TC-19 | PASS | Three surges, 2,100/2,100 accepted each; admission 172.24/168.76/158.32 s, all within 600 s. Max launch lag <0.029 s. Mixed: 40 parties, 32 clients, ten C seats safely allocated. |
| TC-23 fixed load | PASS | Nine trials, 1,500/1,500 each. All requested 1/2/4 pods actually served. Mean trial P95 by replicas: 19.871/16.488/22.142 ms; approximately 50 accepted/s. No automatic speedup claim. |
| TC-23 capacity | PASS at tested points | 20/40/60/80/100/s at 1/2/4 replicas, plus separate 200/s points. All 18 points met declared thresholds. 200/s is the highest passing tested rate, a lower bound rather than a maximum. |
| TC-24 API | PASS | 19,140 accepted; actual Ready 1 -> 4 -> 1 -> 4. Peak high-load CPU 374% of request; recovery CPU 7%. |
| TC-24 worker | PASS | 19,020 accepted; actual Ready 1 -> 4 -> 1 -> 4. Peak CPU 86%, recovery 9.1%. Backlog drained; one Ready worker observed 589.66 s after actual spike offer-end, within 600 s. |

All final performance cohorts above had zero client HTTP failures, generator drops, upstream retries, missing/duplicate IDs and SQL violations. Valid UNAVAILABLE allocations are inventory exhaustion, not paid bookings. A separate post-repeat worker observation found all 19,020 terminal outcomes; it does not substitute for the original recovery checkpoint or prove another automatic scale-in.

### Seven regression families: PASS within recorded scope
TC-14 and TC-15: three fresh repetitions each. TC-16: three repeats at each 1/2/4 worker count, both policies. TC-18: ten independent F1 seeds 42-51, both policies. TC-20: three active and three near-expiry races. TC-21: lost committed reply and abrupt worker crash. TC-22: Redis, PostgreSQL and combined 60-second outages. All 21 top-level variants passed; paired policy work comprises 38 individual replays. Optional F2-F7 explorations are not certified by the final F1 cohort.

Host tests: 77 passed plus four subtests. Real PostgreSQL checks: 131 passed (61 seat, 50 payment, 11 dispatcher, nine booking). Core service sources were unchanged after that SQL preflight. The final independent verification passed 77 new evidence/coverage/continuity checks plus 244 original-workload raw checks: 321 audit checks passed, zero failed. These audit counts are distinct from the 25 case IDs and from the host/PostgreSQL test counts.

<!-- pagebreak -->
## 9.8 Final 25-Case Coverage and Evidence
### Recorded Local Result: 25/25 PASS
Read this evidence map first; Section 9.7 retains measurements and Section 9.9 locates archives and source provenance. Section 10.1 pairs all case IDs with methods and recorded results. Viewing these saved files does not execute a test.

The final ledger records the completed local validation. Fifteen cases have newly completed final-version functional/browser/deployment checks; ten retain their full original-scope final v9 measurements and were independently re-audited. All 96 compared application/configuration files remained unchanged, and captured deployed image IDs matched v9. No application code was changed during the later functional verification.

| Case IDs | Actual result / scope | Final evidence run under .local/test-results/ |
|---|---|---|
| TC-01 to TC-08; TC-10 to TC-12; TC-17; TC-25 | PASS - new final-version checks | all25-audit.json: each listed case's evidence field |
| TC-09 | PASS - completed Compose validation | all25-audit.json: TC-09 evidence |
| TC-13 | PASS - completed seat-outage validation | all25-audit.json: TC-13 evidence |
| TC-14/15/16/18/20/21/22 | PASS - original full regression scope | tc-fix-regression-v9 and its per-case child runs |
| TC-19 | PASS - three original surges and mixed parties | tc-fix-19-v9 |
| TC-23 | PASS - fixed replicas and tested capacity points | tc-fix-23-v9; tc-fix-capacity-v9; tc-fix-capacity-upper-v9 |
| TC-24 | PASS - separate complete automatic cycles | tc-fix-24-api-v9; tc-fix-24-worker-v9 |

The new browser checks include actual refresh of both same-customer tabs, an unchanged five-minute expiry with same-hold late-payment HTTP 409, and TC-25 offline refresh, full browser-process restart, original identity/deadline recovery, administrator sign-in/out and return after real expiry. TC-25 completed 19 checks and eight HTTP 403 denials, including genuine payment/cancellation IDs; no second registration occurred. Its seven-day cookie lifetime is configuration, not a claim of seven elapsed days of testing.

Current 25-case conclusions use the completed evidence above. Both this guide and the updated results report describe the same final ledger.

<!-- pagebreak -->
## 9.9 Environment and Evidence Package

### Tested environment and deployment scope
The final local host/Docker budget reported 12 logical CPUs and approximately 7.69 GiB Docker RAM. Gateway CPU limit=1 core; PostgreSQL limit=2 cores. Other final pod resources, image/source fingerprints and runtime versions are captured in the evidence. Busy or smaller machines may miss deadlines even with the same source.

Kubernetes studies and faults ran in isolated csc3104-lab; TC-09 used a separate Compose project and then stopped that project with volumes retained. Final restoration recorded one replica each, no HPAs, pre-sale, Demand-Cycle, batch 10, TTL 300 and 70 available seats. Main deployment specifications/UIDs were unchanged; retained main dispatcher data was not migrated. Application commit 253a6e2 contains the validated source; the 96 compared application/configuration files match final v9. SOURCE_PROVENANCE.json records the submission source snapshot and documentation/release overlay; use the submitted source, scripts and manifests to build images.

### Follow-up evidence scope

All 64 planned follow-up units are COMPLETE, with no measurement pending. The original 25-case PASS matrix retains its recorded scope. No application tests were rerun for this documentation update.

The saved-data audit passed 1,046 checks with zero failures. Full analysis, counts, waits, denominators and raw paths: docs/FOLLOWUP_EVALUATION_RESULTS.md and output/validation/followup-20261119/report/RESULTS.md. Article table/paragraph and PNG/SVG figures are in that report folder.

### Supporting evidence files
The two PDFs and the raw evidence have different roles. The instructions describe the procedures; the results report summarises outcomes, charts and interpretation; raw records and audits allow independent verification of those findings.

Download the attached GROUP02_Submission.zip from the [submission release page](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest). GitHub's automatically generated Source code ZIP omits ignored raw evidence. Extract the attachment once and work from CSC3104_G2_CloudProject/. Most raw evidence is in this attachment rather than the branch file listing.

| Location inside the extracted project | What it contains |
|---|---|
| output/pdf/ | Testing instructions, results report and their editable sources. |
| .local/test-results/ | Reviewed exported raw runs: logs, request observations, snapshots and screenshots where collected. |
| output/validation/all25/all25-audit.json | Selects the recorded evidence folder supporting each of the 25 cases. |
| output/validation/tc-fixes/ | Validation reports, graphs and audits. |
| output/validation/followup-20261119/ | Follow-up reports, measurement tables and audits. |
| output/tc14-extended-20261119/ | Extended latency observations, summaries, charts and trial checks. |

All evidence paths in this guide are relative to that extracted project folder. Start with START_HERE.md, then open all25-audit.json and follow each case's evidence field. Example names such as TC-01 and TC19-exam are destinations for new manual reruns, not the selected recorded run IDs. Reading saved evidence requires no Docker deployment and generates no new test results.

SUBMISSION_MANIFEST.json hashes each included payload file; SUBMISSION_VERIFICATION.json records packaging checks. The all25 audit folder also retains original-workload checks and environment restoration records. Exported logs are reviewed for credentials; private browser profiles, kubeconfig, generated Secrets and .env.core are excluded. Reviewed evidence is extracted into this package; no nested ZIPs or separate archive downloads are needed.

### Examiner result log
For every case record observed result, run ID, source/image version, machine limits, exact steps, configuration, timestamps, IDs, terminal counts, errors, invariant output, evidence filenames and restoration. Expected results in Section 10 are acceptance conditions; the examiner must enter their own observations. All 25 cases passed the recorded local checks. This does not establish a clean-machine result, production security, storage HA or a guaranteed outcome on another machine.

<!-- pagebreak -->
## 10. Testing Summary Matrix
Expected results are acceptance conditions. Pair rows with Section 10.1 for methods and recorded results; use detailed cases for all thresholds.

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
| TC-24 | Optional HPA | Automatic scaling | Ready 1 -> out -> 1 -> out; drained backlog | Metrics/HPA/events |
| TC-25 | Browser ownership | Access/session recovery | Own booking restored; cross-user denied | Cookies/HTTP/state |

### Result record template
Record Test ID; run ID; source revision/changes; machine limits; policy/replicas/batch/TTL; input trace hash; exact actions; observed terminal counts/status; measured values; evidence filenames; expected-versus-observed differences; restoration completed. Retain run.json and before/after captures when generated. Use new run IDs instead of overwriting failing evidence.

<!-- pagebreak -->
## 10.1 Methods and Recorded Local Results
### Recorded Local Result
Recorded PASS results refer to the previously completed local validation. They are not predictions or guarantees for an examiner's independent execution.

Pair with Section 10 for names, concepts and expected results. Each reference below leads to that case's complete Verification/Evidence fields; Section 9.8 selects the recorded cohort from all25-audit.json.

**Method key:** Manual = UI/inspection; Automated = scripts with operator setup/review; Mixed = manual actions plus scripted/backend checks. Setup may reset lab even for automated tests. These describe the documented procedures.

| Test ID | Testing method | Recorded local result | Verification / detailed evidence |
|---|---|---|---|
| TC-01 | Mixed | PASS | Section 5, TC-01 |
| TC-02 | Mixed | PASS | Section 5, TC-02 |
| TC-03 | Mixed | PASS | Section 5, TC-03 |
| TC-04 | Mixed | PASS | Section 5.1, TC-04 |
| TC-05 | Mixed | PASS | Section 5.1, TC-05 |
| TC-06 | Automated | PASS | Section 5.1, TC-06 |
| TC-07 | Mixed | PASS | Section 6, TC-07 |
| TC-08 | Automated | PASS | Section 6, TC-08 |
| TC-09 | Mixed | PASS | Section 7, TC-09 |
| TC-10 | Mixed | PASS | Section 7, TC-10 |
| TC-11 | Mixed | PASS | Section 8, TC-11 |
| TC-12 | Mixed | PASS | Section 8, TC-12 |
| TC-13 | Mixed | PASS | Section 8.1, TC-13 |
| TC-14 | Automated | PASS | Section 9, TC-14 |
| TC-15 | Automated | PASS | Section 9, TC-15 |
| TC-16 | Automated | PASS | Section 9.1, TC-16 |
| TC-17 | Mixed | PASS | Section 8.1, TC-17 |
| TC-18 | Automated | PASS | Section 9.2, TC-18 |
| TC-19 | Automated | PASS | Section 9.3, TC-19 |
| TC-20 | Automated | PASS | Section 9.3, TC-20 |
| TC-21 | Automated | PASS | Section 9.4, TC-21 |
| TC-22 | Automated | PASS | Section 9.4, TC-22 |
| TC-23 | Automated | PASS | Section 9.4, TC-23 |
| TC-24 | Automated | PASS | Section 9.5, TC-24 |
| TC-25 | Mixed | PASS | Section 9.6, TC-25 |

Record each new outcome independently; retain failures, original workloads, seeds, deadlines, repetitions and safety assertions.

<!-- pagebreak -->
## 11. Troubleshooting and Cleanup
**Inspect first:** get, describe, logs, API status and saved-evidence reads observe state. They do not reset bookings. Avoid publishing secrets from operational output. Use the csc3104-lab-only k helper from Section 4 for commands below; it does not target main.

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

<!-- pagebreak -->
## 11.1 Cleanup and Retained-State Upgrades
### Retained-state dispatcher upgrade
New dispatcher storage separates active work, append-only history and receipts; inline legacy state migrates transactionally. Upgrade waiting-room API first. Quiesce BOTH old dispatcher-api and dispatcher-worker and wait for their pods to exit before starting either new version. Preserve Redis/PostgreSQL volumes. Mixed old/new dispatcher rolling upgrades are unsupported; old binaries cannot hydrate normalized history. A downgrade requires exporting/recombining history first. See experiments/STUDY_PROTOCOLS.md#scaling. Fresh lab resets avoid this migration path; do not reset main storage for these tests.

### Command effects - choose deliberately
- **Inspect:** k get / describe / logs and payment monitor read operational state; preserve evidence before intervention.
- **Restart:** the documented pod deletions and rollout restart commands replace components. Stored records remain on PVCs, but requests can be interrupted. Restrict test actions to csc3104-lab and wait for recovery.
- **Stop, preserve storage:** scaling lab Deployments/StatefulSets to zero below stops processes, retaining PVCs/credentials. Restore original replicas before resuming.
- **Affects main:** python demo.py --kubernetes --stop stops the main Kubernetes deployment; python demo.py --stop stops main Compose. Both preserve storage, but interrupt main service. Do not use them to stop only the lab.
- **WARNING - DELETES LAB DATA:** Section 4's --reset-lab deletes isolated lab namespace data, queue, PVCs and credentials. Export evidence first; restart the lab forward and sign in with its new password afterward. This is distinct from stop/restart. Never delete main storage or the Kind cluster as routine cleanup.

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

**Supporting scripts:** experiments/run.py, study.py, loadgen.py, observability.py, runtime.py, workloads.py, metrics.py, invariants.sql; tests/docker_booking_smoke.py and http_validation_smoke.py. Editable source: output/pdf/GROUP02_INSTRUCTIONS.md; renderer: experiments/build_instructions.py (requires reportlab and pypdf).
