GROUP 02 / CSC3104

# Run the experiment.Know what it proves.

A practical testing handbook for Fair Seat Allocation

Revised 10 November 2026 | Local Kubernetes / Redis / PostgreSQL

| What this revision gives you | How to use it |
| --- | --- |
| 30 case cards with goals, procedures, expected evidence and caveats | Choose the same case ID in Admin > Experiments. |
| Runnable local evidence, contention and replay tools | Use experiments/run.py. Commands target only csc3104-lab. |
| Demand-Cycle and an equivalent FCFS control | Run the same saved trace, fixture and batch boundaries; compare per-group outcomes. |
| An honest readiness map | Ready = runnable procedure. PASS requires your own evidence; missing features stay explicit. |

### Preserve your main demo

Port 18100 and namespace csc3104-lab are for experiments. Port 18090 is the main Kubernetes demo. Resetting a lab erases its data; export results first.

The original downloaded PDF is preserved. This revision replaces outdated shared-tab instructions and missing-FCFS assumptions, while retaining the goals of all eight original testing areas.

## 1. Start with the right claim

### Your end goal

Show repeatable correctness, recovery and measured trade-offs. A test should answer one question, keep its inputs controlled, preserve every outcome and identify the limits of the result.

| Word | Meaning |
| --- | --- |
| Implemented | The source contains a feature. |
| Ready | A runnable procedure/tool exists for this case; it may still fail. |
| PASS | You ran it and every declared acceptance condition passed. |
| FAIL | An observed requirement was violated. |
| BLOCKED | A required feature, checkpoint, tool or environment is absent. |
| INCONCLUSIVE | The run happened, but missing evidence, unknown outcomes or unequal inputs prevent the claim. |
| NOT_RUN | No execution has been recorded for this case/run. |

### Three things the UI cannot certify

A healthy API is not worker progress. A Ready pod is not a successful booking. Browser seat colors are not a substitute for PostgreSQL ownership checks. Use the live workbench to observe, then use CLI snapshots/invariants to corroborate.

### Do not hide a gap

Seven catalog cases remain capability-blocked: six exact distributed crash checkpoints and public authorization. HPA/resources, distributed API scaling and real cloud cost need external setup. They have procedures and goals, but are not represented as passed.

### Stop-and-fix rule

Stop release approval for double live ownership, partial live parties, duplicate successful payment, released confirmed seats, lost acknowledged work or unauthorized access. Preserve the failing state and evidence instead of deleting the problem records.

## 2. Use the experiment workbench

- Open the lab at http://127.0.0.1:18100 and choose Admin > Experiments. Confirm the connected namespace label.

- Pick a case and enter a unique run ID. Open run restores that case/run's checklist, notes and browser snapshots.

- Read End goal, Before starting, Expected evidence and Take note before doing anything.

- Keep Overview, Seat map, Batches and each customer in separate ordinary browser tabs. Each tab keeps its own selected identity/view.

- In My booking, choose an existing ID and View user to inspect it. New user starts a different identity without deleting the earlier booking.

- Capture live snapshots before, during and after faults. Missing observations stay Unavailable, never fabricated zero.

- Import comparison.json, summary.json or an invariant result to inspect CLI measurements in the frontend.

- Enter a manual result with an explanation. Download run evidence; browser storage alone is not a submission archive.

Current workbench: instructions, live observations and operator-entered evidence. Screenshot is illustrative, not a test result.

### Scope of observations

Browser snapshots combine several HTTP observations and are not an atomic database snapshot. HTTP round-trip time is client-to-frontend time, not a service-only benchmark. Payment metrics may combine shared backlog with per-process HTTP counters; a shared heartbeat is not a count of live workers.

## 3. Deployment and experiment commands

### Prepare once

From the repository root, use host Python 3.10+ and Docker Engine 24+ with Linux containers and Compose 2.20+. The launcher downloads its own pinned Kind and kubectl. Allow network access and several GiB of disk; 8 GiB Docker RAM is recommended.

```powershell
python demo.py --kubernetes --check
```

```powershell
python demo.py --kubernetes
```

```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab port-forward --address 127.0.0.1 service/frontend 18100:8080
```

### Reset consciously

The lab command with --reset-lab permanently erases only csc3104-lab before recreating it. Without that flag it updates/preserves the lab. Never replace the namespace with csc3104 or use --reset-demo for routine experiments. Keep the port-forward terminal open; restart it after lab resets.

### Capture a manual experiment

The CLI makes its own temporary loopback port-forward for capture/run commands; it does not need your browser port-forward. It checks that the actual frontend reports csc3104-lab. Exported diagnostics omit Secrets and kubeconfig.

```powershell
python experiments/run.py capture --case W1 --run W1-run1 --phase before
```

```powershell
python experiments/run.py capture --case W1 --run W1-run1 --phase during
```

```powershell
python experiments/run.py capture --case W1 --run W1-run1 --phase after
```

```powershell
python experiments/run.py invariants --run W1-run1
```

### Where evidence goes

CLI results are stored under .local/test-results/<run-id>/. Workload commands require a new run ID and automatically capture before/after snapshots; do not pre-fill their run directory with a manual capture. Manual capture/invariants commands may append to an existing manual run. Browser downloads are separate: move them into the corresponding evidence folder.

## 4. Reading map and source coverage

| Area | Case IDs | Goal |
| --- | --- | --- |
| Booking | B1-B5, Q01 | Identity, payment, cancel, expiry and whole-party capacity |
| Reconnect | B6 / U01 | Independent tabs and same-user idempotency/recovery |
| Correctness/load | C02, Q02, C01, J01 | SQL safety, intake load, direct contention and full journeys |
| Fault recovery | W1, W2, R1-R3 | Saved work, dependency loss and pod persistence |
| Exact crash points | RF1-RF6 | Checkpoint-specific distributed recovery; not yet equipped |
| Research | F01 (F1-F7), S01, S02 | Paired policies, worker count and API replica scaling |
| Cloud/boundaries | A01, COST, SEC01, D01 | Metrics/HPA, cost, authorization and operational interpretation |

### Original scorecard crosswalk

Q01, Q02, C01, C02, F01, S01, S02, A01 and SEC01 retain their IDs. Original P01 is covered by B1-B4. Original R01 is covered by W1/W2; R02 by R2; U01 by B6. B5, R1/R3 and six advanced fault checkpoints retain their explicit procedures. This covers the source handbook's complete 20-page scope, not only its final scorecard.

### Recommended order

SETUP -> B1/B2/B3/B4/B5 -> B6/Q01 -> C02 -> W1/W2/R1/R2/R3 -> low-rate Q02/C01/J01 -> F01 -> S01. Attempt S02/A01/COST only after their measurement setup exists. Keep RF1-RF6 and SEC01 BLOCKED until the missing mechanisms are present.

## SETUP / Prepare an isolated experiment lab

Setup | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Know exactly which system you are testing and start from a documented state.

### Before starting

Python 3.10+, Docker Engine 24+, Compose 2.20+, Linux containers; 8 GiB Docker RAM recommended.

### Procedure

1. Run the prerequisite check from the repository root.

2. Build/load the current images using normal Kubernetes startup.

3. Create or explicitly reset only the lab.

4. Start the lab port-forward and keep its terminal open.

5. Open port 18100; check the Experiments environment label says csc3104-lab.

6. Use separate tabs for Experiments, Overview, Seat map and each user.

### Expected result / acceptance

- Thirteen long-running lab pods Ready, three init jobs Completed, two PVCs Bound.

- The experiment CLI refuses main/unknown frontend environments.

### Take note

- Reset deletes lab data permanently; export evidence first.

- Namespace isolation does not isolate CPU, RAM or whole-node failures.

- Use Ctrl+Shift+R after deploying frontend changes. New user is per tab; existing users stay in the picker.

### Commands - repository root

```powershell
python demo.py --kubernetes --check
```

```powershell
python demo.py --kubernetes
```

```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab port-forward --address 127.0.0.1 service/frontend 18100:8080
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 4, 5. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## B1 / Complete a normal booking

Booking | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Prove one whole party receives exactly its adjacent seats and one final confirmation.

### Before starting

Fresh pre-sale lab; workers running; use a 300-second hold for manual work.

### Procedure

1. My booking > New user: create a fictional customer.

2. Choose A and party size 2; Register and record request ID.

3. In a separate Overview tab, Start sale.

4. Wait for RESERVED; record hold ID, seats and original deadline.

5. Complete mock payment; wait for CONFIRMED.

6. Check Seat map and the authoritative snapshot/invariants.

### Expected result / acceptance

- Exactly two adjacent seats in one row are confirmed for the same request/hold.

- The booking reference does not change after refresh.

### Take note

- A 200 response or a Ready pod is not proof of confirmed seats.

- No actual money or card data is involved.

### Commands - repository root

```powershell
python experiments/run.py capture --case B1 --run B1-run1 --phase before
```

```powershell
python experiments/run.py invariants --run B1-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 5, 6. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## B2 / Decline and deliberately retry

Booking | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Prove a payment retry does not extend the hold or create duplicate effects.

### Before starting

Fresh user with an unpaid RESERVED hold; record its original expiry.

### Procedure

1. Simulate decline.

2. Wait until the server reports the attempt declined.

3. Confirm the seats are not confirmed.

4. Complete mock payment before the original deadline.

5. Compare hold ID, deadline and payment attempts; run invariants.

### Expected result / acceptance

- One declined attempt followed by at most one successful attempt.

- Same hold and original deadline throughout.

### Take note

- Clicking twice while an attempt is pending is a replay, not a deliberate new attempt.

- If expiry wins, a rejection is correct; do not extend the timer to make the test pass.

### Commands - repository root

```powershell
python experiments/run.py invariants --run B2-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 6. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## B3 / Cancel an unpaid reservation

Booking | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Release the entire unpaid party, without releasing confirmed seats.

### Before starting

New user with an unpaid hold; note all assigned seats.

### Procedure

1. Cancel reservation and confirm the demo dialog.

2. Wait for authoritative CANCELLED.

3. Check every original seat in Seat map.

4. Reload the user; confirm it remains cancelled.

5. Run invariants.

### Expected result / acceptance

- All party seats are available; no partial live hold remains.

- Ended request cannot pay or rejoin.

### Take note

- Cancel the unpaid hold, not a different customer or a confirmed booking.

- A cancellation request may first be pending; wait for its final outcome.

### Commands - repository root

```powershell
python experiments/run.py invariants --run B3-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 6. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## B4 / Expire an unpaid hold

Booking | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Prove backend expiry releases the party and prevents late confirmation.

### Before starting

Fresh hold; TTL 300 seconds manually, or use a clearly recorded 30-second lab TTL.

### Procedure

1. Record hold ID and original backend expiry.

2. Do not pay; observe countdown and backend state past the worker scan interval.

3. Refresh until EXPIRED and verify Seat map.

4. Run the expiry acceptance check or inspect the saved late-payment rejection.

5. Run invariants.

### Expected result / acceptance

- Entire party released; no successful payment on the expired hold.

- The same request stays ended after reload.

### Take note

- The frontend intentionally disables expired payment actions; a UI click alone cannot test the rejected HTTP request.

- The automated booking checker sends the actual late payment.

- A zero countdown is not authoritative expiry.

### Commands - repository root

```powershell
python demo.py --kubernetes --verify
```

```powershell
python experiments/run.py invariants --run B4-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 6, 7. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## B5 / No adjacent capacity remains

Booking | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Reject an entire party when a suitable adjacent block does not exist.

### Before starting

Fresh lab. Section C has one row of ten seats in the development fixture.

### Procedure

1. Create three different Section C users, each requesting four seats, before starting sale.

2. Start sale, then inspect each user through the picker.

3. Confirm or keep valid holds alive while checking outcomes.

4. Inspect Seat map and run invariants.

### Expected result / acceptance

- At most two four-person parties fit; another receives UNAVAILABLE.

- No losing party has one, two or three live seats.

### Take note

- Whole-party capacity, not total free seats alone, determines acceptance.

- The losing request depends on queue/policy; record actual positions.

- Do not let early holds expire during the observation.

### Commands - repository root

```powershell
python experiments/run.py invariants --run B5-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 6, 7. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## B6 / Reconnect and use simultaneous browser tabs

Recovery | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Keep the same logical request and deadline across reloads and concurrent same-user actions.

### Before starting

Browser session/local storage enabled; one queued, held or completed test customer.

### Procedure

1. Record request, queue, hold and expiry.

2. Reload this tab; verify the same user/view and IDs.

3. Open a new tab; choose the SAME existing user ID and View user.

4. Keep Overview in another tab; it must stay on Overview.

5. Repeat after confirmed, cancelled, expired and unavailable outcomes.

6. For simultaneous Pay, select the same held user in both tabs and inspect duplicate checks.

### Expected result / acceptance

- Different tabs may select different identities/views independently.

- Same-user tabs share one request and at most one logical payment/cancel effect.

- No terminal state creates a new queue entry.

### Take note

- New tabs do not automatically select your earlier customer; use the picker.

- Switch user opens the picker. New user creates another demo identity only in this tab.

- Selecting another user is a local demo feature, not trusted login.

### Commands - repository root

```powershell
node --test frontend/tests/recovery.test.cjs
```

```powershell
python experiments/run.py invariants --run B6-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 15, 16. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## Q01 / Registration identity and duplicate submit

Queue | READY TO RUN - NOT AN EXECUTED PASS

### End goal

One logical user registration produces one request even when a response is retried.

### Before starting

Pre-sale lab; record a synthetic user ID and a fixed section/party payload.

### Procedure

1. Register the user and record returned request ID.

2. Replay the identical user/payload or run the automated acceptance check.

3. Check queue count and Redis-backed request identity.

4. After sale starts, verify the same request has one queue position.

### Expected result / acceptance

- Duplicate registration returns the original request, without a second queue entry.

- Accepted IDs remain retrievable after recovery.

### Take note

- A new UUID on retry is a different customer, not an idempotency test.

- Unknown responses require reconciliation with the same identity.

### Commands - repository root

```powershell
python demo.py --kubernetes --verify
```

```powershell
python experiments/run.py capture --case Q01 --run Q01-run1 --phase before
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 7, 20. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## C02 / Six seat invariants and payment duplicates

Correctness | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Find impossible ownership, partial parties, non-adjacency and duplicate live effects in PostgreSQL.

### Before starting

Meaningful bookings or failed competing attempts exist; pause new input and let transitions settle.

### Procedure

1. Capture counts and representative request/hold IDs.

2. Run the invariant command.

3. Read all six seat counts and both payment duplicate counts.

4. If any count is nonzero, stop release approval and preserve evidence.

### Expected result / acceptance

- Six seat violation counts are zero; no duplicate pending/successful payment per hold.

- Empty history is INCONCLUSIVE_EMPTY, not proof of contested booking correctness.

### Take note

- Historical reuse of a released seat is legitimate; simultaneous live ownership is the violation.

- Do not fix a failed experiment by deleting bad records.

### Commands - repository root

```powershell
python experiments/run.py invariants --run C02-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 7, 8. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## W1 / Payment API alive while its worker is paused

Faults | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Separate API availability from durable background progress and recovery.

### Before starting

Fresh unpaid hold; 300-second TTL; payment worker initially one replica.

### Procedure

1. Pause payment-worker and wait until no old worker remains.

2. Complete mock payment once.

3. Observe API health, pending attempts, backlog and heartbeat age in Experiments.

4. Restore worker before expiry if testing successful recovery.

5. Verify the original hold/payment settles and run invariants.

### Expected result / acceptance

- The API may remain healthy while saved payment stays pending.

- Recovery uses the same hold and deadline; no duplicate success.

### Take note

- A shared heartbeat is not a per-worker count.

- If the original expiry passes, rejection/expiry is correct.

- Capture before, during and after, not just a green final screen.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment payment-worker --replicas=0
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab wait --for=delete pod -l app=payment-worker --timeout=90s
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment payment-worker --replicas=1
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status deployment/payment-worker --timeout=180s
```

```powershell
python experiments/run.py capture --case W1 --run W1-run1 --phase before
```

```powershell
python experiments/run.py invariants --run W1-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 9. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## W2 / Pause the allocation worker before dispatch

Faults | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Observe durable unfinished allocation and recovery of the same job.

### Before starting

Fresh pre-sale lab, registered users, no dispatch yet.

### Procedure

1. Pause allocation-worker and wait for old worker pods to disappear.

2. Start sale.

3. Observe unfinished jobs in Batches and the CLI backlog snapshot.

4. Restore allocation-worker.

5. Verify original requests reach RESERVED/UNAVAILABLE and run invariants.

### Expected result / acceptance

- Same saved job/request resolves; no second live hold.

- Other sections remain logically independent.

### Take note

- Pause before dispatch; a job that finished before pause does not test saved-work recovery.

- One active job per section and one active dispatcher batch limit parallelism.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment allocation-worker --replicas=0
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab wait --for=delete pod -l app=allocation-worker --timeout=90s
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment allocation-worker --replicas=1
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status deployment/allocation-worker --timeout=180s
```

```powershell
python experiments/run.py capture --case W2 --run W2-run1 --phase before
```

```powershell
python experiments/run.py invariants --run W2-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 9. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## R1 / Graceful payment-worker restart

Faults | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Verify a normal worker replacement does not lose saved work.

### Before starting

Saved payment and recorded IDs; know whether it is still pending.

### Procedure

1. Capture the original payment.

2. Restart payment-worker and wait for rollout.

3. Refresh the same user.

4. Capture the final state and run invariants.

### Expected result / acceptance

- Same payment reaches a legitimate terminal result without duplicate effect.

### Take note

- If work finished before restart, record graceful restart only.

- A rolling restart does not prove an abrupt after-commit crash.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout restart deployment/payment-worker
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status deployment/payment-worker --timeout=180s
```

```powershell
python experiments/run.py capture --case R1 --run R1-run1 --phase before
```

```powershell
python experiments/run.py invariants --run R1-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 10. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## R2 / Replace PostgreSQL and Redis pods

Faults | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Retain booking/payment/queue records and the same PVC identities after storage process replacement.

### Before starting

At least one confirmed booking, saved IDs, before snapshot and PVC UIDs.

### Procedure

1. Capture before state.

2. Replace only the two lab storage pods.

3. Wait for both StatefulSets.

4. Reopen the same customer and compare final seats, history, queue and PVC UIDs.

5. Complete a new booking to test reconnection; capture after and run invariants.

### Expected result / acceptance

- Data and PVC UIDs survive; clients reconnect.

- New booking works after recovery.

### Take note

- This is same-volume pod persistence, not node/disk-loss HA or backup/restore.

- Do not delete a PVC, namespace or Kind cluster.

### Commands - repository root

```powershell
python experiments/run.py capture --case R2 --run R2-run1 --phase before
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab delete pod postgres-0 redis-0
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status statefulset/postgres --timeout=180s
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status statefulset/redis --timeout=180s
```

```powershell
python experiments/run.py invariants --run R2-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 10. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## R3 / Seat API unavailable during saved payment

Faults | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Prevent false success and preserve the original operation while a dependency is down.

### Before starting

Fresh hold, sufficient time before expiry, initial replicas recorded.

### Procedure

1. Pause payment-worker, then submit Pay so the work is saved.

2. Pause seat-api.

3. Restore payment-worker and observe pending/retry work while seat-api is absent.

4. Capture outage state.

5. Restore seat-api.

6. Verify the original payment outcome and run invariants.

### Expected result / acceptance

- No false confirmation or erroneous no-capacity decision during the outage.

- After restoration, legitimate confirmation or expiry uses original IDs/deadline.

### Take note

- An API error is not proof that a payment failed.

- Record recovery time from dependency restoration until saved work resolves, not just pod readiness.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment payment-worker --replicas=0
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment seat-api --replicas=0
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment payment-worker --replicas=1
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment seat-api --replicas=1
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status deployment/seat-api --timeout=180s
```

```powershell
python experiments/run.py capture --case R3 --run R3-run1 --phase before
```

```powershell
python experiments/run.py invariants --run R3-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 10. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## RF1 / Hold committed but allocator loses its response

Advanced faults | CAPABILITY BLOCKED

### End goal

Recover the exact hold ID and original expiry.

### Before starting

Requires a controlled checkpoint/response-loss fixture; random pod deletion is insufficient.

### Procedure

1. Design and record the exact checkpoint.

2. Run existing unit/contract tests as supporting evidence.

3. Implement the distributed injection fixture before attempting the Kubernetes case.

4. Capture commit, interruption, retry and authoritative final state.

### Expected result / acceptance

- A checkpoint proves hold commit before response loss, then original request retry reconciles the hold.

- Seat/payment invariants stay valid.

### Take note

- Mark BLOCKED until the distributed checkpoint can be proven.

- Unit mocks do not establish that a real Kubernetes execution hit this point.

- Allocator BLOCKED-work repair remains a missing operator feature.

### Commands - repository root

```powershell
python -m unittest discover -s src/allocation/tests -v
```

```powershell
python experiments/run.py capture --case RF1 --run RF1-run1 --phase before
```

```powershell
python experiments/run.py invariants --run RF1-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 11. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## RF2 / Confirmation committed but payment loses its response

Advanced faults | CAPABILITY BLOCKED

### End goal

Recover one confirmation, without another successful effect.

### Before starting

Requires a controlled checkpoint/response-loss fixture; random pod deletion is insufficient.

### Procedure

1. Design and record the exact checkpoint.

2. Run existing unit/contract tests as supporting evidence.

3. Implement the distributed injection fixture before attempting the Kubernetes case.

4. Capture commit, interruption, retry and authoritative final state.

### Expected result / acceptance

- A checkpoint proves seat confirmation committed before the worker missed its reply.

- Seat/payment invariants stay valid.

### Take note

- Mark BLOCKED until the distributed checkpoint can be proven.

- Unit mocks do not establish that a real Kubernetes execution hit this point.

- Allocator BLOCKED-work repair remains a missing operator feature.

### Commands - repository root

```powershell
python -m unittest discover -s src/allocation/tests -v
```

```powershell
python experiments/run.py capture --case RF2 --run RF2-run1 --phase before
```

```powershell
python experiments/run.py invariants --run RF2-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 11. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## RF3 / Batch accepted but dispatcher loses its response

Advanced faults | CAPABILITY BLOCKED

### End goal

Continue the same batch without duplicate admission.

### Before starting

Requires a controlled checkpoint/response-loss fixture; random pod deletion is insufficient.

### Procedure

1. Design and record the exact checkpoint.

2. Run existing unit/contract tests as supporting evidence.

3. Implement the distributed injection fixture before attempting the Kubernetes case.

4. Capture commit, interruption, retry and authoritative final state.

### Expected result / acceptance

- Record the receiver commit, lost response and replay of the same batch ID/input.

- Seat/payment invariants stay valid.

### Take note

- Mark BLOCKED until the distributed checkpoint can be proven.

- Unit mocks do not establish that a real Kubernetes execution hit this point.

- Allocator BLOCKED-work repair remains a missing operator feature.

### Commands - repository root

```powershell
python -m unittest discover -s src/allocation/tests -v
```

```powershell
python experiments/run.py capture --case RF3 --run RF3-run1 --phase before
```

```powershell
python experiments/run.py invariants --run RF3-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 11. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## RF4 / Release committed while callback receiver is down

Advanced faults | CAPABILITY BLOCKED

### End goal

Keep seats released and retry the durable callback.

### Before starting

Requires a controlled checkpoint/response-loss fixture; random pod deletion is insufficient.

### Procedure

1. Design and record the exact checkpoint.

2. Run existing unit/contract tests as supporting evidence.

3. Implement the distributed injection fixture before attempting the Kubernetes case.

4. Capture commit, interruption, retry and authoritative final state.

### Expected result / acceptance

- Record release commit and the saved outbox event; receiver outage must begin before callback delivery.

- Seat/payment invariants stay valid.

### Take note

- Mark BLOCKED until the distributed checkpoint can be proven.

- Unit mocks do not establish that a real Kubernetes execution hit this point.

- Allocator BLOCKED-work repair remains a missing operator feature.

### Commands - repository root

```powershell
python -m unittest discover -s src/allocation/tests -v
```

```powershell
python experiments/run.py capture --case RF4 --run RF4-run1 --phase before
```

```powershell
python experiments/run.py invariants --run RF4-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 11. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## RF5 / Old worker returns after its lease was replaced

Advanced faults | CAPABILITY BLOCKED

### End goal

Reject the stale fenced acknowledgment.

### Before starting

Requires a controlled checkpoint/response-loss fixture; random pod deletion is insufficient.

### Procedure

1. Design and record the exact checkpoint.

2. Run existing unit/contract tests as supporting evidence.

3. Implement the distributed injection fixture before attempting the Kubernetes case.

4. Capture commit, interruption, retry and authoritative final state.

### Expected result / acceptance

- Hold the old worker past lease expiry, record the new token, then release the old response.

- Seat/payment invariants stay valid.

### Take note

- Mark BLOCKED until the distributed checkpoint can be proven.

- Unit mocks do not establish that a real Kubernetes execution hit this point.

- Allocator BLOCKED-work repair remains a missing operator feature.

### Commands - repository root

```powershell
python -m unittest discover -s src/allocation/tests -v
```

```powershell
python experiments/run.py capture --case RF5 --run RF5-run1 --phase before
```

```powershell
python experiments/run.py invariants --run RF5-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 11. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## RF6 / Poison work followed by valid work

Advanced faults | CAPABILITY BLOCKED

### End goal

Expose invalid/blocked work and demonstrate its documented repair/independence.

### Before starting

Requires a controlled checkpoint/response-loss fixture; random pod deletion is insufficient.

### Procedure

1. Design and record the exact checkpoint.

2. Run existing unit/contract tests as supporting evidence.

3. Implement the distributed injection fixture before attempting the Kubernetes case.

4. Capture commit, interruption, retry and authoritative final state.

### Expected result / acceptance

- Inject a known invalid job through a controlled fixture; record BLOCKED state and recovery procedure.

- Seat/payment invariants stay valid.

### Take note

- Mark BLOCKED until the distributed checkpoint can be proven.

- Unit mocks do not establish that a real Kubernetes execution hit this point.

- Allocator BLOCKED-work repair remains a missing operator feature.

### Commands - repository root

```powershell
python -m unittest discover -s src/allocation/tests -v
```

```powershell
python experiments/run.py capture --case RF6 --run RF6-run1 --phase before
```

```powershell
python experiments/run.py invariants --run RF6-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 11. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## Q02 / Registration ramp, spike and backlog

Load | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Measure offered intake, completed registration RPS, latency, rejected/unknown outcomes and retained IDs.

### Before starting

Fresh empty pre-sale lab per run; generator and host capacity documented.

### Procedure

1. Run a short low-rate calibration.

2. Repeat constant rates 5, 10, 25, 50, 100/s only while capacity permits.

3. Reset between independent runs.

4. Use spike profile for low-high-low arrival segments.

5. Reconcile accepted/uncertain identities and export all arrivals, including generator drops.

### Expected result / acceptance

- Every offered arrival is accounted for: accepted, rejected, unknown or not launched.

- Acknowledged request IDs remain the same on identity reconciliation.

### Take note

- Registration RPS is not completed bookings/s or seat contention.

- Browser Simulate users is a convenience, not a calibrated load generator.

- Port-forward/frontend bottlenecks and generator drops must be reported.

### Commands - repository root

```powershell
python experiments/run.py register --rate 5 --duration 10 --run Q02-baseline
```

```powershell
python experiments/run.py register --rate 25 --duration 30 --profile spike --run Q02-spike
```

### Record

Offered and launched counts; achieved RPS; p50/p95/p99; per-status totals; unknowns and dropped arrivals; accepted-ID reconciliation; resource samples.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 11, 12, 19, 20. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## C01 / Direct seat-store contention: C1-C4

Load | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Send overlapping hold requests to real PostgreSQL-backed seat transactions and check whole-party safety.

### Before starting

Fresh lab; Section C has ten available seats; no other seat activity.

### Procedure

1. Run C1 with 10 one-seat requests and 10 client workers.

2. Save every response and timing window.

3. Run invariants and inspect Section C.

4. Reset and repeat with 50, 100 and, only after calibration, 500 requests.

### Expected result / acceptance

- No more than ten seats are live; no seat has two live owners.

- No partial/duplicate live party; every client result is accounted for.

### Take note

- This intentionally bypasses waiting-room/allocator/payment to isolate seat-store concurrency.

- Client request overlap is not proof of an equal number of simultaneously running database transactions.

- Full-journey replay is a different test; its per-section scheduler serializes allocations.

### Commands - repository root

```powershell
python experiments/run.py contention --count 10 --workers 10 --run C1
```

```powershell
python experiments/run.py contention --count 50 --workers 20 --run C2
```

```powershell
python experiments/run.py invariants --run C01-run1
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 12, 13. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## J01 / Replay the full booking journey

Load | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Account for each saved customer from registration to allocation and mock-payment/cancel/expiry outcome.

### Before starting

Fresh lab, fixed saved trace, declared policy/replicas/batch/TTL, all original queue positions recorded.

### Procedure

1. Create and save a seeded trace.

2. Prepare the lab with the declared TTL and batch size.

3. Run replay; it sets the lab lottery from saved queue order before sale starts.

4. Wait for all outcomes or the declared deadline.

5. Inspect per-customer CSV/JSON and invariants; retain unknowns.

### Expected result / acceptance

- Actual observed queue positions and batch boundaries match the trace.

- All customers have accounted outcomes; safety checks remain zero.

### Take note

- Saved client seed alone cannot reproduce SystemRandom numbering; replay applies and verifies the saved lab lottery.

- Decision timing comes from saved allocator outcomes; missing timings stay missing.

- A timeout is an unknown, not UNAVAILABLE.

### Commands - repository root

```powershell
python experiments/run.py trace --scenario F1 --count 12 --seed 42 --output .local/traces/F1-42.json
```

```powershell
python experiments/run.py replay --trace .local/traces/F1-42.json --run J01
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 12, 13. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## F01 / Paired Demand-Cycle versus FCFS: F1-F7

Fairness | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Measure policy trade-offs using identical trace, queue, inventory, batches, actions and execution resources.

### Before starting

Saved trace; explicit --reset-lab permission; record worker count, batch size, TTL and fixture.

### Procedure

1. Generate F1 balanced, F2 70% size-1, F3 70% size-4, F4 80% section-A with independent sizes, F5 scarce, F6 fragmented, or F7 cancellation/expiry trace.

2. Run paired comparison; it resets only the lab before each policy and verifies the initial seat fingerprint.

3. Keep all non-policy inputs equal and alternate policy order on repeats.

4. Inspect per-section/party-size sample sizes, acceptance, waits, overtakes, fragmentation and unknowns.

5. Repeat with ten saved seeds where feasible; preserve all results and variation.

### Expected result / acceptance

- Both policies visit the exact same queue positions within the same fixed batches and use unchanged seat-store transactions.

- Claims reflect measured trade-offs; Demand-Cycle need not win.

### Take note

- The comparator changes ALLOCATION_POLICY only in the lab; normal main deployment stays Demand-Cycle.

- FCFS is per-section/per-batch, with the same cross-section worker concurrency.

- Report reservation versus final confirmation separately; include initial fixture occupancy.

- A one-pair smoke run is not a statistical fairness conclusion.

### Commands - repository root

```powershell
python experiments/run.py trace --scenario F1 --count 12 --seed 42 --output .local/traces/F1-42.json
```

```powershell
python experiments/run.py compare --trace .local/traces/F1-42.json --reset-lab --hold-ttl 30 --run F01-pair
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 14, 15. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## S01 / Allocation workers: 1, 2, 3, 4 and 8

Scaling | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Measure useful throughput and bottlenecks with only worker count changing.

### Before starting

Same saved balanced and hot-section traces; same policy, fixture, limits, batch/TTL per run.

### Procedure

1. Reset lab before each independent run.

2. Scale only allocation-worker; wait for rollout.

3. Run the same full-journey trace.

4. Collect decision jobs/s, reserved parties, confirmed bookings, duration, backlog, DB connections and resource samples.

5. Repeat each count at least three times and compare variation.

### Expected result / acceptance

- Speedup = T(1)/T(n); efficiency = speedup/n, with declared workload and complete outcomes.

- No duplicate/partial ownership while workers scale.

### Take note

- At most four section jobs can be active; hot-section load may use only one.

- One active dispatcher batch adds another ceiling.

- Fast UNAVAILABLE decisions are not useful reservations; graph them separately.

- k top requires working metrics-server.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment allocation-worker --replicas=2
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status deployment/allocation-worker --timeout=180s
```

```powershell
python experiments/run.py replay --trace .local/traces/F1-42.json --run S01-workers2
```

```powershell
python experiments/run.py capture --case S01 --run S01-run1 --phase before
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 13, 14, 20. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## S02 / Waiting-room API replicas: 1, 2 and 4

Scaling | NEEDS SETUP

### End goal

Measure API scaling with verified request distribution and fixed resources.

### Before starting

A repeatable intake trace and a traffic path that actually distributes to API replicas.

### Procedure

1. Scale only waiting-room; wait for all desired replicas.

2. Run the same registration workload.

3. Record per-pod traffic and achieved/dropped arrivals.

4. Compare RPS, p95/p99, errors, backlog and resources.

5. Repeat configurations at least three times.

### Expected result / acceptance

- Results include achieved traffic and per-pod evidence.

- Safety/identity checks hold across replicas.

### Take note

- Frontend connection pools or port-forward may concentrate traffic; neither proves balanced ingress.

- Current admission controller records traffic but does not enforce adaptive permits.

- Without per-pod distribution evidence, mark scaling attribution INCONCLUSIVE.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab scale deployment waiting-room --replicas=2
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab rollout status deployment/waiting-room --timeout=180s
```

```powershell
python experiments/run.py register --rate 5 --duration 10 --run S02-two
```

```powershell
python experiments/run.py capture --case S02 --run S02-run1 --phase before
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 13, 20. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## A01 / Fixed replicas versus CPU HPA

Cloud | NEEDS SETUP

### End goal

Observe requested versus Ready replicas and actual service quality through idle, steady, peak and recovery phases.

### Before starting

A separate agreed disposable cluster, working metrics-server, calibrated load and HPA resource requests.

### Procedure

1. Verify metrics API and top pods work before enabling HPA.

2. Record fixed 1/2/4 replica baselines.

3. Apply HPA only to lab waiting-room.

4. Replay the same offered traffic and record desired/Ready replica timelines, latency/errors and resources.

5. Delete the lab HPA and restore the original fixed count.

### Expected result / acceptance

- Actual requested and Ready replicas are recorded alongside end-to-end quality.

- Missing metrics means BLOCKED, not zero CPU or no scale demand.

### Take note

- HPA does not create more node capacity in local Kind.

- Do not install cluster-wide metrics/HPA components into an unrelated user cluster without an agreed setup.

- CPU HPA target is a configuration, not a measured result.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab get --raw /apis/metrics.k8s.io/v1beta1
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab top pods
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab autoscale deployment waiting-room --cpu=70% --min=1 --max=4
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab get hpa
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab delete hpa waiting-room
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Delete only the lab waiting-room HPA and restore the recorded replica count. Keep the metrics setup separate from unrelated workloads.

Original handbook pages: 16, 20. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## COST / Resource and hosting-cost interpretation

Cloud | NEEDS SETUP

### End goal

Report resource use and attributable cost per confirmed booking without inventing cloud spend.

### Before starting

Measured resources, confirmed-booking counts, run duration and a chosen provider/region/pricing date if estimating.

### Procedure

1. Record node/pod resources across the same workload phases.

2. Separate allocated resource requests from measured usage.

3. For local Kind, label money as a modelled estimate.

4. For a real chosen provider, include compute, storage, gateway and transfer costs.

5. Divide attributable cost by confirmed bookings, or report N/A if none confirmed.

### Expected result / acceptance

- Every money value has units, provider/region/date and assumptions.

- No fabricated invoice or division by zero.

### Take note

- This task does not provision a paid cloud environment.

- Do not present requests/limits as actual usage.

- Fairness or load runs on a laptop do not establish production cost.

### Commands - repository root

```powershell
python experiments/run.py capture --case COST --run COST-run1 --phase before
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab top pods
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 16, 17, 18. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## SEC01 / Public authorization boundary

Security | CAPABILITY BLOCKED

### End goal

Verify anonymous/admin separation and prevent customers accessing another customer's booking.

### Before starting

Trusted login, scoped customer/admin authorization and checkout-token delivery must be implemented first.

### Procedure

1. Document the current local demo boundary.

2. List anonymous sale/admin, cross-customer read/pay/cancel, forged/expired token, callback access and replay cases.

3. After authorization is implemented, test through the real frontend/gateway, not only internal services.

4. Verify denied operations cause no state change.

### Expected result / acceptance

- Public-ready behavior: unauthorized calls denied with no data leakage or saved action.

- Current demo must not be marked PASS for customer/admin access prevention.

### Take note

- The user picker deliberately permits demo identity switching; it is not authentication.

- Keep ports loopback/private and do not enter real payment data.

- Token checks on an internal payment service do not fix a frontend that adds its own service token for everyone.

### Commands - repository root

```powershell
python experiments/run.py capture --case SEC01 --run SEC01-run1 --phase before
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 16, 20. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## D01 / Readiness, configuration and resource inspection

Operations | READY TO RUN - NOT AN EXECUTED PASS

### End goal

Know what green health signals do and do not demonstrate.

### Before starting

Deployed lab with expected config and pod/job inventory.

### Procedure

1. Check pods, init jobs, PVCs, configured replicas and limits.

2. Compare API health/readiness with actual worker progress.

3. Inspect non-secret settings and stable Service addresses.

4. Record dependency outages separately from liveness.

5. Only report measured CPU/memory when a metrics provider exists.

### Expected result / acceptance

- Completed Jobs and Ready running pods are interpreted correctly.

- No credentials are copied into screenshots or evidence bundles.

### Take note

- Ready background pods alone do not prove useful work.

- Do not export Kubernetes Secrets or kubeconfig.

- Metrics errors must stay unavailable, not display zero.

### Commands - repository root

```powershell
python infra/k8s/kubectl.py -n csc3104-lab get pods,pvc,services,jobs
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab get configmap core-config -o yaml
```

```powershell
python infra/k8s/kubectl.py -n csc3104-lab top pods
```

```powershell
python experiments/run.py capture --case D01 --run D01-run1 --phase before
```

### Record

User/request/hold IDs; original expiry; before/during/after UTC times; screenshots; invariant results.

### After the experiment

Restore paused components to their recorded replica counts. Run invariants and capture the final state.

Original handbook pages: 5, 14, 17. Default result: NOT_RUN (or BLOCKED where a prerequisite is absent).

## 5. Run a paired policy study

### What changes

The lab allocator reads ALLOCATION_POLICY=demand-cycle or fcfs. FCFS visits original queue positions within the same section and batch. Worker claims, section serialization, seat-store first-fit adjacency, holds, payment and database transactions are unchanged. The main deployment remains Demand-Cycle.

### What is replayed

The trace saves scenario/seed, synthetic identity, independent section/party size, queue number, action/delay, wave and batch size. Before opening the pre-sale queue, the CLI invokes a lab-only Redis fixture to replace lottery scores with that saved order. The fixture is not an HTTP endpoint and rejects non-lab use. Later-wave customers are submitted sequentially in saved order while dispatch is briefly paused.

```powershell
python experiments/run.py trace --scenario F1 --count 40 --seed 42 --batch-size 10 --output .local/traces/F1-42.json
```

```powershell
python experiments/run.py compare --trace .local/traces/F1-42.json --reset-lab --hold-ttl 30 --replicas 1 --repeats 3 --run F01-seed42
```

```powershell
python experiments/run.py trace --scenario F6 --count 40 --seed 42 --output .local/traces/F6-42.json
```

```powershell
python experiments/run.py compare --trace .local/traces/F6-42.json --reset-lab --hold-ttl 120 --run F06-seed42
```

### Inventory controls

F1-F4 and F7 start empty. F5 confirms 80% of each section using seat-store-owned operations. F6 first fills single-seat holds and then confirms odd positions/cancels even positions, leaving alternating gaps; use TTL >=120 seconds for fixture preparation. Initial occupied seat IDs/states are fingerprinted and must match across policies. Fixture bookings are excluded from offered-customer denominators and reported separately in inventory counts.

### Repetitions

Within one --repeats run, policy order alternates. That is repeated execution of one saved trace, not multiple independent seeds. For research, generate ten separate saved seeds per scenario where feasible and use unique run IDs. Report variation and unknowns; do not select only a favorable pair.

### Remaining boundaries

RF1-RF6 exact commit/response-loss injection and public authorization are not added by replay. Full-journey replay measures this single-node deployment; it is not a cloud-scale result or a proof that all high-concurrency transactions overlap.

## 6. Metrics you can defend

| Metric | Definition / caution |
| --- | --- |
| Party reservation rate | Reserved parties / all valid offered parties in the same section and size. Keep rejected, unknown and unfinished counts visible. |
| Final confirmation rate | Confirmed parties / offered parties. Separate payment behavior from allocation decisions. |
| Decision wait | Allocator PostgreSQL decided_at minus Redis eligible_at. Both RESERVED and UNAVAILABLE outcomes receive timestamps. Missing/negative timing is not zero and makes the result inconclusive. |
| Overtakes | Pairs where a later original queue position is decided earlier, only within the same section and actual fixed batch. Include unsuccessful decisions. |
| Full replay throughput | Completed allocation decisions / client-observed replay wall time, including registration/action/drain. Not isolated service capacity. |
| Worker speedup / efficiency | For the same trace/resources, speedup(n)=T(1)/T(n); efficiency(n)=speedup/n. Report useful reservations as well as decisions. |
| Fragmentation | Free contiguous block lengths per row; never merge rows. Fewer free seats alone is not a fragmentation measure. |
| RPS and p95/p99 | Use actual individual HTTP samples and achieved offered traffic. Generator drops remain in the account; tail percentiles from tiny samples are unstable. |
| Recovery time | Time from dependency restoration until the original saved operation resolves, in addition to pod-ready time. |
| Cost / confirmed booking | Attributable billed cost / confirmed bookings; N/A when zero confirm. Local Kind monetary estimates are not invoices. |

### Clock and sampling notes

Redis and PostgreSQL timestamps are wall-clock measurements; synchronized clocks are required. The lab normally shares one VM clock. Save eligibility/decision timestamps and flag negative intervals. Browser snapshots are multi-call observations. Do not compare incomplete runs as though every customer had an observed final wait.

## 7. Evidence and honest submission

| Output | What it establishes |
| --- | --- |
| run.json / before.json / after.json | Command audit, namespace, commit/dirty-diff fingerprint, safe configuration, pod/PVC identities, replicas, backlog and available observations. |
| trace.json | The exact saved research input; retain SHA-256 and seed. |
| customers.csv / customers.json | Every replay or direct-contention customer, including errors and unknowns. |
| arrivals.csv / arrivals.json | Every scheduled registration arrival, including those the generator did not launch. |
| summary.json | Per-run outcomes/metrics and declared scope; interpret tool status within that scope. |
| comparison.json | Both policy runs, input/initial-inventory comparison and full result details. Import this in the workbench. |
| invariants-*.json | Six seat checks, payment duplicate counts and meaningful-data counts. Empty history is inconclusive. |
| Browser evidence download | Operator result/notes/checklist and captured browser observations; not a replacement for SQL/CLI evidence. |

### One run, one declared claim

Record case ID, date/time zone, code version plus dirty state, trace hash, inventory fingerprint, policy, worker/API replicas, batch size, hold TTL, resource limits, offered and observed counts, invariant violations, result and evidence paths. Preserve timed-out/failed runs. A smoke run is implementation validation, not a full statistical experiment.

### Recommended plots

Plot offered concurrency against reserved/unavailable/unknown outcomes; policy acceptance and median/p95 wait by section and size; worker count against useful reservations and decisions/s; API replicas against achieved intake and tail latency; fault timelines from pending backlog to recovery. Include sample sizes, repetitions and resource limits on every plot.

### Current validation ledger

See experiments/VALIDATION.md and the saved local result folders for executions from this revision. Case cards intentionally do not pre-fill PASS. CI configuration alone is not a recorded CI pass. The original handbook's historical successful log is separate evidence and does not automatically validate the new research tools.

## 8. Troubleshooting and prerequisites

| Symptom | Next action |
| --- | --- |
| Port 18100 unavailable | Restart the lab port-forward terminal; inspect lab pods/events. Do not reset storage to fix a disconnected terminal. |
| Frontend says main/unknown environment | Stop the experiment. Use the lab service and rebuild current images; CLI environment guard should reject the target. |
| Run directory already has evidence | Choose a new workload run ID. Manual capture can append phases to a manual run. |
| Replay queue or batch mismatch | Keep evidence; check trace batch size, unexpected registrations, dispatch timing and the actual saved queue. Do not call the pair comparable. |
| Payment API healthy but pending grows | Inspect worker replica count, heartbeat age, backlog and original expiry. Restore only the intended lab component. |
| Old customer after reset | My booking > New user for a new identity. Opening an old ID does not revive its deleted backend records. |
| k top / metrics API fails | Metrics provider is absent/unready. CPU/memory/HPA observations remain BLOCKED or unavailable. |
| Too many workers do not help | Check four-section serialization, one active batch, DB locks, shared CPU and frontend/port-forward limits. |
| Counter seems lower after restart | Per-process HTTP counters reset. Shared durable backlog is a different metric. |
| Browser says expired, seat still held | Wait for authoritative worker processing; inspect exact hold and database, then run invariants. |

### External setup still required

A01 requires an agreed disposable metrics/HPA installation; S02 needs a traffic path and per-pod evidence for load distribution. COST needs measured resources and an actual chosen provider/pricing basis. SEC01 requires a real trusted authorization layer. No paid services or public exposure are provisioned by this revision.

## 9. Sources and maintenance

- User-supplied GROUP02_Complete_Testing_Handbook.pdf, all 20 pages, version 9 November 2026. The original file is unchanged.

- Current repository: TESTING.md; demo.py; infra/k8s/local.py; frontend/static; allocation algorithm/job store; waiting-room Redis store; payment monitoring; seat-store transaction API.

- experiments/catalog.py is the case source. Run python experiments/catalog.py after edits to publish frontend/static/experiments.json.

- experiments/build_handbook.py produces this PDF and editable Markdown from that same case catalog. Re-render and inspect after changes.

### Kubernetes HPA

https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/

### Resource metrics pipeline

https://kubernetes.io/docs/tasks/debug/debug-cluster/resource-metrics-pipeline/

### Liveness, readiness and startup probes

https://kubernetes.io/docs/concepts/workloads/pods/probes/

### k6 constant-arrival-rate executor

https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/

### Before presenting to the professor

Use a fresh checkout and the documented minimum prerequisites. Confirm the submission commit's CI results and save a second-machine verification. Demonstrate the basic booking flow first, then one bounded fault and one paired research example. Present remaining setup/capability gaps explicitly.
