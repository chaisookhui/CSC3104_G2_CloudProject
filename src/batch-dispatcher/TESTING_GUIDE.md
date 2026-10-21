# Three-Module Ticketing Integration Test Runbook

**Scope:** Waiting Room (5001) → Batch Dispatcher (5003) → **Mock** Allocator (5002) → Waiting Room. The real allocator, SeatStore (planned 5005), Waitlist-Payment (5004), frontend, and real seat/payment logic are **out of scope**.

**Code assumption:** This guide targets the *proposed revised implementations* with `POST /queue/outcomes`, `POST /allocator/status`, `GET /batches/history`, and the separate `mock_allocator.py`. Verify these routes exist in your running code. The dispatcher and mock keep in-memory state; use a **fresh/reset Waiting Room state** and restart all three processes for a clean run.

**Success criteria:** Batches of 50, 50, 20 are processed in strictly increasing global queue positions, without overlap; outcome sync is atomic; each mock completion leads to **one** next batch; terminal requests are never requeued; no new batch starts before the previous result sync completes.

## 0. Terminals, startup and localhost URLs

Keep **four** PowerShell terminals (service folders may differ in your repository):

**Terminal A — Waiting Room**

```powershell
$env:DISPATCHER_URL = 'http://localhost:5003'
python app.py
```

**Terminal B — Batch Dispatcher**

```powershell
$env:WAITING_ROOM_URL = 'http://localhost:5001'
$env:ALLOCATOR_URL = 'http://localhost:5002'
$env:BATCH_SIZE = '50'
python app.py
```

**Terminal C — Mock Allocator** (the folder containing `mock_allocator.py` and `algorithm.py`)

```powershell
$env:DISPATCHER_URL = 'http://localhost:5003'
python mock_allocator.py
```

**Terminal D — Test commands:**

```powershell
$WR = 'http://localhost:5001'
$D  = 'http://localhost:5003'
$A  = 'http://localhost:5002'
```

| Module | Localhost GET endpoint | What it shows |
|---|---|---|
| Waiting Room | http://localhost:5001/queue | Sale state, request IDs, unique queue numbers and request statuses |
| Dispatcher | http://localhost:5003/status | `active_batch_id`, `batch_state`, `batch_history` |
| Dispatcher | http://localhost:5003/batches/current | Details of currently active batch (404 if none) |
| Dispatcher | http://localhost:5003/batches/allocator-input | Exact flat allocator payload for active batch (404 if none) |
| Dispatcher | http://localhost:5003/batches/history | All in-memory batch records and states |
| Mock Allocator | http://localhost:5002/health | `service: mock-allocation` |
| Mock Allocator | http://localhost:5002/batches/batch-0001 | Batch 1 `complete`, `jobs`, `size_order` |
| Mock Allocator | http://localhost:5002/batches/batch-0002 | Batch 2 after it is created |
| Mock Allocator | http://localhost:5002/batches/batch-0003 | Batch 3 after it is created |

**Check services before test:**

```powershell
Invoke-RestMethod "$A/health"
Invoke-RestMethod "$D/status" | Format-List
Invoke-RestMethod "$WR/queue" | Select-Object sale_state, count
```

If localhost is unavailable, check that all three services started, the port is correct, and port 5002 is occupied by **mock**, not the real allocator. `GET` addresses can be opened in a browser; **`POST` actions require PowerShell**.

## 1. Reusable PowerShell inspection and assertion helpers

Paste once into **Terminal D**. They do **not** modify service state.

```powershell
function Show-QueueCounts {
    $q = Invoke-RestMethod "$WR/queue"
    "Sale: $($q.sale_state) | Queue records: $(@($q.requests).Count)"
    $q.requests | Group-Object status | Sort-Object Name |
        Select-Object Name, Count | Format-Table -AutoSize
}

function Show-BatchState {
    $s = Invoke-RestMethod "$D/status"
    "Active batch: $($s.active_batch_id) | Dispatcher state: $($s.batch_state)"
    Invoke-RestMethod "$D/batches/history" | ConvertTo-Json -Depth 12
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    "PASS: $Message"
}

function Assert-QueueCounts([int]$Reserved, [int]$Unavailable,
                            [int]$Admitted, [int]$Queued, [int]$Registered = 0) {
    $records = @((Invoke-RestMethod "$WR/queue").requests)
    $counts = @{}
    foreach ($r in $records) {
        if (-not $counts.ContainsKey($r.status)) { $counts[$r.status] = 0 }
        $counts[$r.status]++
    }
    foreach ($entry in @(@('RESERVED',$Reserved), @('UNAVAILABLE',$Unavailable),
                        @('ADMITTED',$Admitted), @('QUEUED',$Queued),
                        @('REGISTERED',$Registered))) {
        $actual = 0
        if ($counts.ContainsKey($entry[0])) { $actual = [int]$counts[$entry[0]] }
        Assert-True ($actual -eq [int]$entry[1]) "$($entry[0]) = $($entry[1]) (actual $actual)"
    }
    Assert-True ($records.Count -eq ($Reserved+$Unavailable+$Admitted+$Queued+$Registered)) `
        'No missing or unaccounted-for queue records'
}

function Assert-UniqueQueueNumbers {
    $requests = @((Invoke-RestMethod "$WR/queue").requests)
    $numbers = @($requests | Where-Object { $null -ne $_.queue_number } |
                 ForEach-Object { [int]$_.queue_number })
    $unique = @($numbers | Sort-Object -Unique)
    Assert-True ($unique.Count -eq $numbers.Count) 'No duplicate queue numbers'
}

function Assert-BatchMembership([string]$BatchId, [int]$ExpectedCount,
                                [int]$ExpectedFirst, [int]$ExpectedLast) {
    $payload = Invoke-RestMethod "$D/batches/allocator-input"
    Assert-True ($payload.batch_id -eq $BatchId) "$BatchId is active"
    $reqs = @($payload.requests)
    Assert-True ($reqs.Count -eq $ExpectedCount) "$BatchId has $ExpectedCount requests"
    $positions = @($reqs | ForEach-Object { [int]$_.global_position } | Sort-Object)
    Assert-True ($positions[0] -eq $ExpectedFirst) "$BatchId first queue number = $ExpectedFirst"
    Assert-True ($positions[-1] -eq $ExpectedLast) "$BatchId last queue number = $ExpectedLast"
    Assert-True ((@($positions | Sort-Object -Unique)).Count -eq $ExpectedCount) `
        "$BatchId has no repeated positions"
    $actualCounts = @{}
    foreach ($r in $reqs) {
        if (-not $actualCounts.ContainsKey($r.section)) {
            $actualCounts[$r.section] = @{'1'=0;'2'=0;'3'=0;'4'=0}
        }
        $actualCounts[$r.section][[string]$r.party_size]++
    }
    Assert-True ((@($payload.section_demand.PSObject.Properties)).Count -eq $actualCounts.Count) `
        'Demand contains exactly the represented sections'
    foreach ($section in $actualCounts.Keys) {
        foreach ($size in 1..4) {
            $reported = [int]$payload.section_demand.$section."$size"
            Assert-True ($reported -eq $actualCounts[$section]["$size"]) `
                "Demand $section/size $size matches request count"
        }
    }
}
```

**Note on queue positions:** The first 50 admitted to Batch 1 have global queue positions 1–50 even though *which user ID* gets a particular number is randomized at sale start.

## 2. Register 120 users **before** sale start

**Precondition:** Fresh/reset Waiting Room with sale state `pre_sale` and no users. Registering with an existing user ID may return the previous record instead of adding a new request.

```powershell
$sections = @('A','B','C','D')
for ($i = 1; $i -le 120; $i++) {
    $body = @{
        user_id    = "test_user_$i"
        section    = $sections[($i-1) % 4]
        party_size = (([int][math]::Floor(($i-1)/4) + (($i-1)%4)) % 4) + 1
    } | ConvertTo-Json
    Invoke-RestMethod -Uri "$WR/submit" -Method POST `
        -ContentType 'application/json' -Body $body | Out-Null
}
Show-QueueCounts
Assert-QueueCounts 0 0 0 0 120
```

**Open:** http://localhost:5001/queue

**Validate:** `sale_state` is `pre_sale`; 120 request records; all `REGISTERED`; queue numbers are `null`/unset. All four sections and party sizes 1–4 should be represented.

**Optional data validation:**

```powershell
$q = Invoke-RestMethod "$WR/queue"
$q.requests | Group-Object section | Select-Object Name,Count
$q.requests | Group-Object party_size | Select-Object Name,Count
```

## 3. Start sale: Batch 1 should start automatically

**Action (only once per fresh sale):**

```powershell
Invoke-RestMethod -Uri "$WR/sale/start" -Method POST |
    ConvertTo-Json -Depth 10
```

**Open, in this order:**

1. http://localhost:5001/queue — sale started, 120 unique queue positions 1–120; 50 `ADMITTED`, 70 `QUEUED`.
2. http://localhost:5003/status — `active_batch_id = batch-0001`, `batch_state = WAITING_FOR_ALLOCATION`.
3. http://localhost:5003/batches/current — first batch contains 50 requests.
4. http://localhost:5003/batches/allocator-input — correct `batch_id`, 50 flat requests, `section_demand`, **no dispatcher-side size ranking**.
5. http://localhost:5002/batches/batch-0001 — `complete = false`, 50 jobs awaiting manual completion.
6. http://localhost:5003/batches/history — exactly one created batch.

**Assertions:**

```powershell
Assert-QueueCounts 0 0 50 70
Assert-UniqueQueueNumbers
Assert-BatchMembership 'batch-0001' 50 1 50
$one = Invoke-RestMethod "$A/batches/batch-0001"
Assert-True (-not $one.complete) 'Mock Batch 1 is not complete yet'
Assert-True (@($one.jobs).Count -eq 50) 'Mock Batch 1 has 50 jobs'
```

### 3A. Prevent premature Batch 2

With Batch 1 still open, try:

```powershell
try {
    Invoke-RestMethod -Uri "$D/batches/next" -Method POST -ErrorAction Stop
    throw 'FAIL: Dispatcher allowed Batch 2 prematurely'
} catch {
    if ($_.Exception.Message -like 'FAIL:*') { throw }
    'PASS (inspect HTTP status; expected 409): Cannot start a new batch while Batch 1 active'
}
```

**Validate:** http://localhost:5003/status still shows `batch-0001`; history still has only one batch; queue counts remain 50 `ADMITTED` and 70 `QUEUED`. The expected HTTP status is **409**; the `catch` block above only proves an error occurred, so inspect the exception's status if it differs.

## 4. Manually complete Batch 1 — mixed outcomes

**Action:**

```powershell
try {
    Invoke-RestMethod -Uri "$A/test/batches/batch-0001/complete" `
      -Method POST -ContentType 'application/json' `
      -Body '{"unavailable_count":10}' -ErrorAction Stop |
      ConvertTo-Json -Depth 10
} catch {
    Write-Warning "Mock completion returned an HTTP error or timed out: $($_.Exception.Message)"
    Write-Warning 'Inspect ALL three services before retrying; completion may already have committed.'
}
```

**Open:**

1. http://localhost:5002/batches/batch-0001 — `complete = true`; exactly 40 jobs `RESERVED`, 10 `UNAVAILABLE`, 0 `CANCELLED`.
2. http://localhost:5001/queue — **40 `RESERVED`, 10 `UNAVAILABLE`, 50 new `ADMITTED`, 20 `QUEUED`**.
3. http://localhost:5003/batches/history — Batch 1 `COMPLETED`, Batch 2 created once.
4. http://localhost:5003/status — `active_batch_id = batch-0002`, `batch_state = WAITING_FOR_ALLOCATION`.
5. http://localhost:5003/batches/allocator-input — Batch 2 positions 51–100, 50 requests.
6. http://localhost:5002/batches/batch-0002 — `complete = false`, 50 pending jobs.

**Assertions:**

```powershell
$one = Invoke-RestMethod "$A/batches/batch-0001"
Assert-True ($one.complete) 'Batch 1 completed in mock'
Assert-True (@($one.jobs | Where-Object state -eq 'RESERVED').Count -eq 40) '40 reserved in mock'
Assert-True (@($one.jobs | Where-Object state -eq 'UNAVAILABLE').Count -eq 10) '10 unavailable in mock'
Assert-QueueCounts 40 10 50 20
Assert-BatchMembership 'batch-0002' 50 51 100
```

**Critical integrity check:** Match the mock's 50 Batch 1 request IDs to Waiting Room, not just aggregate totals.

```powershell
$q = Invoke-RestMethod "$WR/queue"
$jobs = @( (Invoke-RestMethod "$A/batches/batch-0001").jobs )
foreach ($j in $jobs) {
    $matching = @($q.requests | Where-Object request_id -eq $j.request_id)
    Assert-True ($matching.Count -eq 1) "Found exactly one waiting-room record for $($j.request_id)"
    Assert-True ($matching[0].status -eq $j.state) `
        "Waiting Room status for $($j.request_id) = $($j.state)"
}
```

### If you see `Read timed out (read timeout=10)`

A callback timeout **does not prove failure**. Your previous run showed Batch 2 created even though the mock reported a timeout. **Do not restart or blindly resend.** First inspect `5002/batches/batch-0001`, `5003/status`, `5003/batches/history`, and `5001/queue`, and run the assertions above.

- If all assertions pass and Batch 2 exists: **record callback-ack timeout as a known defect**, but **do not retry Batch 1**; proceed to Batch 2.
- If Batch 1 completed but some Batch 1 requests remain `ADMITTED`, or Batch 2 was not created: record **FAIL**; inspect Dispatcher terminal and batch state; do not force `/batches/next` while Batch 1 is unresolved.
- If Dispatcher is in `RESULT_FETCH_FAILED` or `OUTCOME_SYNC_FAILED`, a retry of the **identical** completion command can be attempted after the dependency is healthy. The event ID is reused; do not change `unavailable_count`.

## 5. Manually complete Batch 2 — all RESERVED

**Action:**

```powershell
try {
    Invoke-RestMethod -Uri "$A/test/batches/batch-0002/complete" `
      -Method POST -ContentType 'application/json' `
      -Body '{"unavailable_count":0}' -ErrorAction Stop |
      ConvertTo-Json -Depth 10
} catch { Write-Warning $_.Exception.Message }
```

**Open:**

1. http://localhost:5002/batches/batch-0002 — 50 `RESERVED`, `complete = true`.
2. http://localhost:5001/queue — 90 RESERVED, 10 UNAVAILABLE, 20 ADMITTED, 0 QUEUED.
3. http://localhost:5003/batches/history — Batch 1 and 2 completed; Batch 3 opened.
4. http://localhost:5003/status — `batch-0003` is active.
5. http://localhost:5003/batches/allocator-input — 20 requests, global positions 101–120.
6. http://localhost:5002/batches/batch-0003 — 20 incomplete jobs.

**Assertions:**

```powershell
Assert-QueueCounts 90 10 20 0
Assert-BatchMembership 'batch-0003' 20 101 120
Assert-True (-not (Invoke-RestMethod "$A/batches/batch-0003").complete) 'Batch 3 awaiting completion'
```

## 6. Manually complete Batch 3 — final partial batch

**Action:**

```powershell
try {
    Invoke-RestMethod -Uri "$A/test/batches/batch-0003/complete" `
      -Method POST -ContentType 'application/json' `
      -Body '{"unavailable_count":5}' -ErrorAction Stop |
      ConvertTo-Json -Depth 10
} catch { Write-Warning $_.Exception.Message }
```

**Open:**

1. http://localhost:5002/batches/batch-0003 — 15 `RESERVED`, 5 `UNAVAILABLE`, complete.
2. http://localhost:5001/queue — 105 RESERVED, 15 UNAVAILABLE; **0 ADMITTED, 0 QUEUED**.
3. http://localhost:5003/batches/history — **three** batches, all completed.
4. http://localhost:5003/status — `active_batch_id = null`; `batch_state` may be `QUEUE_EMPTY` (or a completed/idle state depending on implementation).
5. http://localhost:5003/batches/current — expected HTTP **404** (no active batch).

**Assertions:**

```powershell
Assert-QueueCounts 105 15 0 0
Assert-UniqueQueueNumbers
$s = Invoke-RestMethod "$D/status"
Assert-True ($null -eq $s.active_batch_id) 'No active batch at end'
$history = Invoke-RestMethod "$D/batches/history"
Assert-True (@($history.history).Count -eq 3) 'Exactly three batches created'
Assert-True (@($history.history | Where-Object state -eq 'COMPLETED').Count -eq 3) `
    'All three batches completed'
```

**Expected outcome table:**

| Batch | Queue positions | Size | RESERVED | UNAVAILABLE |
|---|---|---:|---:|---:|
| `batch-0001` | 1–50 | 50 | 40 | 10 |
| `batch-0002` | 51–100 | 50 | 50 | 0 |
| `batch-0003` | 101–120 | 20 | 15 | 5 |
| **Total** | **1–120** | **120** | **105** | **15** |

## 7. Additional safety and edge-case tests

### 7A. Duplicate callback after success — must NOT create Batch 4

**Run after completing all three batches:**

```powershell
$before = (Invoke-RestMethod "$D/batches/history").total_batches
try {
    Invoke-RestMethod -Uri "$A/test/batches/batch-0001/complete" `
      -Method POST -ContentType 'application/json' `
      -Body '{"unavailable_count":10}' -ErrorAction Stop | Out-Null
} catch { Write-Warning "Retry returned $($_.Exception.Message); check state" }
$after = (Invoke-RestMethod "$D/batches/history").total_batches
Assert-True ($after -eq $before) 'Duplicate completion created no extra batch'
Assert-QueueCounts 105 15 0 0
```

**Open:** http://localhost:5003/batches/history and http://localhost:5001/queue. Mock may report an HTTP problem, but dispatcher must not create duplicate batches or mutate terminal outcomes.

### 7B. Conflicting mock completion — expect rejection

**Action:** Retrying Batch 1 with a *different* outcome count must be rejected by mock:

```powershell
try {
    Invoke-RestMethod -Uri "$A/test/batches/batch-0001/complete" `
      -Method POST -ContentType 'application/json' `
      -Body '{"unavailable_count":9}' -ErrorAction Stop
    throw 'FAIL: Conflicting completion accepted'
} catch {
    if ($_.Exception.Message -like 'FAIL:*') { throw }
    'PASS (verify HTTP 409): Conflicting completion was rejected'
}
```

**Validate:** Batch 1 still shows 40/10; final queue remains 105/15.

### 7C. Waiting Room atomic outcome idempotency — expect success on exact replay

**Only after Batch 1 has completed:**

```powershell
$jobs = @((Invoke-RestMethod "$A/batches/batch-0001").jobs)
$outcomes = @($jobs | ForEach-Object { @{request_id=$_.request_id; status=$_.state} })
$payload = @{batch_id='batch-0001'; outcomes=$outcomes} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "$WR/queue/outcomes" -Method POST `
  -ContentType 'application/json' -Body $payload
```

**Validate:** Return HTTP 200 (or equivalent idempotent success), queue counts unchanged. Replaying a mismatched status should return **409** with *no partial changes*. The endpoint must validate the whole batch before any update.

### 7D. Invalid or incomplete outcome payload — expect rejection without mutation

```powershell
$bad = @{batch_id='batch-0001'; outcomes=@(@{request_id='does-not-exist';status='RESERVED'})} |
    ConvertTo-Json -Depth 10
try {
    Invoke-RestMethod -Uri "$WR/queue/outcomes" -Method POST `
      -ContentType 'application/json' -Body $bad -ErrorAction Stop
    throw 'FAIL: Invalid outcome payload was accepted'
} catch {
    if ($_.Exception.Message -like 'FAIL:*') { throw }
    'PASS (verify HTTP 409): Incomplete/unknown batch outcome was rejected'
}
Assert-QueueCounts 105 15 0 0
```

### 7E. Invalid mock batch submission — expect validation error

```powershell
$badBatch = @{batch_id='invalid-001'; requests=@(); section_demand=@{}} |
    ConvertTo-Json -Depth 10
try {
    Invoke-RestMethod -Uri "$A/batches" -Method POST `
      -ContentType 'application/json' -Body $badBatch -ErrorAction Stop
    throw 'FAIL: Mock accepted invalid empty batch'
} catch {
    if ($_.Exception.Message -like 'FAIL:*') { throw }
    'PASS (verify HTTP 400): Invalid empty batch rejected'
}
```

### 7F. Reopening sale — should NOT restart Batch 1

**Run after sale is started:**

```powershell
$before = (Invoke-RestMethod "$D/batches/history").total_batches
Invoke-RestMethod -Uri "$WR/sale/start" -Method POST | ConvertTo-Json -Depth 10
$after = (Invoke-RestMethod "$D/batches/history").total_batches
Assert-True ($before -eq $after) 'Repeated sale/start creates no duplicate batch'
```

### 7G. Preserving the global queue across batches

**Open:** http://localhost:5003/batches/history and http://localhost:5001/queue.

**Validate:** Three disjoint sets of request IDs; exactly 50, 50, 20 entries; all 120 IDs occur exactly once in allocator submissions; Batch 1 queue positions 1–50, Batch 2 51–100, Batch 3 101–120. **Do not** infer fairness from the original user IDs; pre-sale queue numbers were randomised.

### 7H. Request input validation (isolated fresh-state test)

Before starting a sale in a separate fresh run, check malformed submissions (invalid section E, party size 0 or 5, absent user ID). Each should be rejected with a 4xx and should not create a queue entry. For duplicate `user_id`, verify your current Waiting Room's intended idempotent behaviour. These checks depend on the actual Waiting Room request-validation code and should not be treated as passed without observing responses.

### 7I. All UNAVAILABLE batch (separate fresh-state test)

Register at least 51 users, start sale, then:

```powershell
Invoke-RestMethod -Uri "$A/test/batches/batch-0001/complete" `
  -Method POST -ContentType 'application/json' `
  -Body '{"unavailable_count":50}'
```

**Validate:** 50 terminal `UNAVAILABLE`, none automatically requeued; if eligible users remain, Batch 2 starts under this **mock test assumption**. This does **not** test the planned SeatStore-confirmed sold-out pause.

### 7J. Delayed completion (separate fresh-state test)

Start sale and **do not** call the mock completion endpoint yet. Refresh http://localhost:5003/status and http://localhost:5002/batches/batch-0001 several times manually. Batch 1 must remain active/incomplete and Batch 2 must not exist. Then complete Batch 1 and confirm exactly one automatic transition to Batch 2.

## 8. Fault-injection scenarios requiring a test hook or controlled dependency interruption

**These are required for stronger reliability evidence, but cannot all be deterministically simulated by the current endpoints alone.** Keep them as *NOT TESTED* until a controllable failure mechanism exists; do not claim they passed just because the happy path passed.

| Test | How to inject in an isolated run | Required result |
|---|---|---|
| Callback timeout | Delay Dispatcher callback response beyond mock's 10s timeout | Mock may return 503; completed outcomes correct; no duplicate next batch; identical retry harmless |
| Waiting Room outcome update times out | Block/delay `POST /queue/outcomes` temporarily | Dispatcher remains paused/uncertain; no next batch until outcome sync acknowledged; retry same payload safely |
| Dispatcher cannot GET mock results | Make `GET /batches/{batch_id}` return temporary 503 | Dispatcher does not update Waiting Room or start next batch; callback retry can recover |
| Allocator submission response lost | Mock accepts POST but drops/delays response | Dispatcher does not create a different batch ID; reconcile/retry identical original submission before advancing |
| Callback repeated during active synchronisation | Deliver identical event concurrently | Only one outcome application and one next batch (in-memory lock must serialise) |
| Incorrect callback counts | Submit valid-looking callback with wrong aggregate counts | Reject; leave Waiting Room unchanged; do not advance |
| Incomplete or mismatched detailed jobs | Mock returns `complete=false` or missing/extra request ID | Reject; no outcome sync or next batch |
| `CANCELLED` allocator job | Mock/test fixture reports a `CANCELLED` job | Dispatcher must not silently treat it as `UNAVAILABLE`; requires agreed policy |
| Claim response lost | Waiting Room applies `/queue/claim` but response times out | Dispatcher holds active batch as uncertain; no duplicate claim/batch; reconciliation still needed |
| Dispatcher or mock process restart | Restart one process during active batch | **Known limitation:** in-memory state lost; test cannot be marked recovered |
| Inventory pause/resume | Requires SeatStore availability status and events | **Out of scope** for this three-module test |

**Current known issue:** Your earlier mock callback returned `Read timed out (read timeout=10)` even though Dispatcher advanced to Batch 2. Classify this as a **callback acknowledgement reliability defect**. If all reconciliation checks pass, the batch-flow functional test may pass **with a known defect**, but the reliable callback-delivery test must remain **FAIL** until fixed and retested.

## 9. Test recording template

Copy this section for each clean test run:

```text
Test date/time:
Commit / code version:
Waiting Room storage: Memory / Redis (specify)
Services: Waiting Room 5001 | Dispatcher 5003 | Mock Allocator 5002
Fresh database/store and fresh processes: YES / NO

[ ] Service startup and health checked
[ ] 120 preregistrations; pre-sale statuses correct
[ ] Sale randomisation; queue numbers unique 1-120
[ ] Batch 1 automatically created, 50 requests
[ ] Correct exact allocator payload and per-section counts
[ ] No premature Batch 2
[ ] Batch 1: 40 RESERVED, 10 UNAVAILABLE
[ ] Individual mock jobs match Waiting Room outcome records
[ ] Batch 2 automatically created once: positions 51-100
[ ] Batch 2: 50 RESERVED
[ ] Batch 3 automatically created once: positions 101-120
[ ] Batch 3: 15 RESERVED, 5 UNAVAILABLE
[ ] Final totals: 105 RESERVED / 15 UNAVAILABLE
[ ] Queue empty; no active batch; three completed batches
[ ] Exact duplicate callback does not advance a new batch
[ ] Conflicting completion is rejected
[ ] Waiting Room outcomes replay is idempotent
[ ] Invalid/incomplete outcome batch rejected atomically
[ ] Invalid mock batch submission rejected
[ ] Duplicate /sale/start creates no batch
[ ] All-UNAVAILABLE test (fresh isolated run)
[ ] Delayed-completion test (fresh isolated run)
[ ] Network and crash fault-injection tests (mark N/T if not implemented)

Observed callback timeouts / HTTP errors:
URLs and JSON evidence captured:
Pass / Fail / Pass with known defect:
Open defects / next actions:
```

## 10. Scope and limitations

- `RESERVED` means **simulated allocation success** here; no real seats are held.
- `UNAVAILABLE` means **simulated individual allocation failure**; it does not indicate global sold-out.
- Automatic frontend rejoin, latecomer admission and waitlist/payment lifecycles are not tested.
- Section D is in the mock allocator's supported sections, but SeatStore's supplied database map still needs a separate future change.
- This runbook assumes the revised code snippets were pasted into your local app. If your actual `/status` keys or response shapes differ, inspect live JSON and adjust the assertions rather than assuming a pass.
- For a reliable final end-to-end test, resolve callback timeout, restore/reconciliation after uncertain sends, and inventory-driven pause/resume separately.
