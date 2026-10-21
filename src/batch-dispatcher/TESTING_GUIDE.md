# Waiting Room + Batch Dispatcher — Testing Guide

> **Scope:** Part 2 (Waiting Room, port `5001`) + Part 4 (Batch Dispatcher, port `5003`) only. **Preview mode:** no calls to the actual allocator and no real seats reserved. The `finish-preview` endpoint **simulates** allocation completion and updates waiting-room statuses.
>
> **Terminal:** VS Code PowerShell on Windows. Commands below are copy-paste ready.

## 0. Before you begin

- Your Waiting Room `app.py` should expose `POST /submit`, `POST /sale/start`, `GET /queue`, `GET /status`, and `POST /queue/claim` / `POST /queue/complete`.
- Your **preview-only** Batch Dispatcher `app.py` should expose `POST /batches/next`, `GET /batches/current`, `GET /batches/allocator-input`, `GET /status`, and `POST /batches/<batch_id>/finish-preview`.
- `GET /batches/history` is **optional**: use the snippet in §8 if your dispatcher doesn't yet have it. History summaries may already be shown at `/status`.
- Use a **fresh waiting-room state** for a clean run. Restarting Flask alone **does not clear Redis data**. Don't delete a shared Redis queue; use a dedicated test queue or reset only your own test data.
- Install required dependencies in the appropriate virtual environments (e.g. `pip install flask requests` if not installed).

## 1. Start services (separate VS Code terminals)

**Terminal 1 — Waiting Room** (from `services/waiting-room`):

```powershell
$env:DISPATCHER_URL = "http://localhost:5003"
python app.py
```

Expected Flask address: `http://localhost:5001`.

**Terminal 2 — Batch Dispatcher** (from `batch-dispatcher`):

```powershell
$env:WAITING_ROOM_URL = "http://localhost:5001"
$env:BATCH_SIZE = "50"
# Do not configure an allocator endpoint in preview mode.
Remove-Item Env:ALLOCATOR_URL -ErrorAction SilentlyContinue
python app.py
```

Expected Flask address: `http://localhost:5003`.

**Browser checks:**
- Waiting Room status: http://localhost:5001/status
- Dispatcher status: http://localhost:5003/status

> If using the *sale-start auto-trigger* modification, **both servers must be running before** you call `/sale/start`. The waiting room calls `/batches/next` exactly on the first successful sale opening in the normal, non-error flow. Later calls to `/sale/start` should not trigger more batches.

## 2. Register 120 users (Terminal 3, PowerShell)

The following party-size pattern varies independently of section so you can inspect meaningful counts.

```powershell
$wr = "http://localhost:5001"
$bd = "http://localhost:5003"
$sections = @("A", "B", "C", "D")

for ($i = 1; $i -le 120; $i++) {
    $section = $sections[($i - 1) % 4]
    $partySize = (([int][math]::Floor(($i - 1) / 4) + (($i - 1) % 4)) % 4) + 1
    $body = @{
        user_id    = "batch_test_user_$i"
        section    = $section
        party_size = $partySize
    } | ConvertTo-Json

    Invoke-RestMethod -Uri "$wr/submit" -Method POST `
        -ContentType "application/json" -Body $body | Out-Null
}
Write-Host "Submitted 120 test requests"
```

**Browser:** http://localhost:5001/queue

Expected **before sale**: `sale_state = "pre_sale"`, `count = 120`; entries are `REGISTERED` and `queue_number = null`.

> If you get existing entries back for these user IDs or the sale is already open, you're not using a fresh test state. Don't trust the expected counts until the state is reset safely.

## 3. Open sale: randomise positions and auto-trigger Batch 1

```powershell
Invoke-RestMethod -Uri "$wr/sale/start" -Method POST | ConvertTo-Json -Depth 8
```

Expected key fields (on a fresh 120-request queue): `sale_state = "sale_started"`, `initial_count = 120`, `next_queue_number = 121`. **If auto-trigger is installed**, response should also indicate the dispatcher was triggered successfully.

**Browser checks:**
- http://localhost:5001/queue — positions `1..120` after shuffling. Positions `1..50` should be `ADMITTED`, while `51..120` remain `QUEUED` after the automatic Batch 1 claim.
- http://localhost:5003/batches/current — `batch-0001`, `batch_size = 50`.
- http://localhost:5003/batches/allocator-input — the **final preview** of section/party-size request counts and lists, not an actual allocator call.

**Test trigger-once behavior:**

```powershell
Invoke-RestMethod -Uri "$wr/sale/start" -Method POST | ConvertTo-Json -Depth 8
```

Expected: sale already started; Batch 1 remains active and **no Batch 2 appears**. Don't manually call `/batches/next` to start Batch 1 if the automatic trigger already worked.

## 4. Inspect the would-be allocator input

**Browser:** http://localhost:5003/batches/allocator-input

Verify:
- There is **no `party_size_priority` field** and no demand-ranking operation in Part 4.
- Section keys `A`, `B`, `C`, `D` exist.
- For each section, `request_count` equals the sum of `demand_counts` for party sizes `1..4`.
- For each party size, `requests_by_party_size` contains that many requests.
- Every request preserves `request_id`, `batch_id`, `global_position`, `section`, `party_size`.
- Across all sections, exactly **50 unique requests** appear in Batch 1.

**PowerShell count verification:**

```powershell
$p = Invoke-RestMethod -Uri "$bd/batches/allocator-input" -Method GET
$total = 0
foreach ($s in @("A", "B", "C", "D")) {
    $section = $p.sections.$s
    $sum = 0
    Write-Host "`nSection $s: $($section.request_count) requests"
    foreach ($size in 1..4) {
        $expected = [int]$section.demand_counts."$size"
        $items = @($section.requests_by_party_size."$size")
        $actual = @($items | Where-Object { $null -ne $_ }).Count
        Write-Host "  Size $size = $expected (list: $actual)"
        if ($expected -ne $actual) { Write-Host "  FAIL: list/count mismatch" -ForegroundColor Red }
        $sum += $expected
    }
    if ($sum -ne [int]$section.request_count) {
        Write-Host "FAIL: section count mismatch" -ForegroundColor Red
    }
    $total += $sum
}
Write-Host "`nTotal across sections: $total; batch size: $($p.batch_size)"
```

**Expected:** total = `50`; all count/list checks match; no priority field. Actual section counts vary because registration is shuffled.

## 5. Check premature next-batch prevention

While Batch 1 is active, run:

```powershell
try {
    Invoke-RestMethod -Uri "$bd/batches/next" -Method POST
} catch {
    Write-Host "HTTP:" ([int]$_.Exception.Response.StatusCode)
}
```

Expected: HTTP **409** because Batch 1 is still active. Browser: http://localhost:5003/batches/current still shows `batch-0001`.

## 6. Simulate Batch 1 ending; open Batch 2

**Terminal 3** (preview only — no allocator involved):

```powershell
Invoke-RestMethod -Uri "$bd/batches/batch-0001/finish-preview" -Method POST
Invoke-RestMethod -Uri "$bd/batches/next" -Method POST
```

**Browser checks:**
- http://localhost:5001/queue — positions `1..50` now `ALLOCATION_DONE` (simulation only); `51..100` now `ADMITTED`; `101..120` remain `QUEUED`.
- http://localhost:5003/batches/current — `batch-0002`, 50 requests, positions `51..100`.
- http://localhost:5003/batches/allocator-input — Batch 2's grouped request counts and individual requests.
- http://localhost:5003/status — history should have Batch 1 finished, Batch 2 active.

> This preview implementation requires a manual `/batches/next` after `/finish-preview`. **Do not** send two `/batches/next` calls if your local version has been modified to auto-start the next batch.

## 7. Simulate Batch 2 ending; open Batch 3

```powershell
Invoke-RestMethod -Uri "$bd/batches/batch-0002/finish-preview" -Method POST
Invoke-RestMethod -Uri "$bd/batches/next" -Method POST
```

**Browser checks:**
- http://localhost:5003/batches/current — `batch-0003`, **20** requests, global positions `101..120`.
- http://localhost:5003/batches/allocator-input — should show 20 total grouped requests, with no ranking.
- http://localhost:5001/queue — `1..100` simulated `ALLOCATION_DONE`; `101..120` `ADMITTED`.

**Optional: finish final batch**

```powershell
Invoke-RestMethod -Uri "$bd/batches/batch-0003/finish-preview" -Method POST
```

Then http://localhost:5003/status should show no active batch. On a fresh queue, Part 2's http://localhost:5001/status should show `queued_count = 0`.

## 8. View batch history

**Already available (summary):** http://localhost:5003/status — inspect `batch_history`.

**Optional dedicated URL:** http://localhost:5003/batches/history

If `/batches/history` returns **404**, add this to `batch-dispatcher/app.py` **above** `if __name__ == "__main__":` and restart the dispatcher (note: restarting clears its in-memory history, so add this **before** running the test):

```python
@app.get("/batches/history")
def get_batch_history():
    with lock:
        return jsonify({
            "total_batches": len(batch_history),
            "active_batch_id": (
                active_batch["batch_id"] if active_batch else None
            ),
            "history": batch_history
        }), 200
```

Expected overview before ending Batch 3:

| Batch | Global positions | Size | State |
|---|---|---:|---|
| `batch-0001` | 1–50 | 50 | Preview finished |
| `batch-0002` | 51–100 | 50 | Preview finished |
| `batch-0003` | 101–120 | 20 | Active preview |

> Exact `state` label strings vary by implementation. The history shown by `/status` usually holds summary metadata, **not** archived request-by-request payloads. Save `/batches/allocator-input` output for each batch **before finishing it**.

### Save each batch's preview to a JSON file (recommended)

Before finishing each batch, run:

```powershell
$active = Invoke-RestMethod -Uri "$bd/batches/allocator-input" -Method GET
$active | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 "allocator-preview-$($active.batch_id).json"
```

This creates `allocator-preview-batch-0001.json`, etc. in the current terminal's working folder.

## 9. Quick success checklist

- [ ] Sale opening randomises once and auto-triggers **Batch 1 once**.
- [ ] Waiting Room `/queue` shows `ADMITTED` for the 50 claimed entries.
- [ ] Batch 1 contains global positions `1..50`.
- [ ] Part 4 returns **only section-by-party-size counts and request lists**; no `party_size_priority`.
- [ ] Sum of all counts equals the batch size; no duplicate IDs.
- [ ] `/batches/next` is rejected while a batch is active.
- [ ] Preview finish updates Waiting Room to `ALLOCATION_DONE` **for testing only**.
- [ ] Batch 2 positions `51..100`, Batch 3 `101..120` (20 requests).
- [ ] `/status` contains the batch-history summary.
- [ ] **No allocator service is called and no seats are reserved.**

## 10. Troubleshooting

| Symptom | Likely reason / next step |
|---|---|
| `404` at `/` | Root route isn't defined. Open `/status`, `/queue`, or `/batches/current` instead. |
| `409 Batch already in progress` | Current batch is active. Finish its preview before advancing. |
| `No eligible requests` | Sale not started, no `QUEUED` entries, or all entries were already admitted/finished. |
| `503` from dispatcher | Check Waiting Room terminal, URL/port, and claim endpoint response. |
| Waiting Room still shows all `QUEUED` after dispatch | Dispatcher claim call or Part 2 `/queue/claim` may not be wired correctly. |
| No Batch 1 after `/sale/start` | Check the auto-trigger change, both servers running, and waiting-room terminal logs. |
| Unexpected IDs/queue counts | Pre-existing waiting-room state, repeated registrations, or non-fresh Redis data. |
| History disappears after restart | Dispatcher history is currently in Python memory, not persisted. |

**Test boundary:** This guide verifies Part 2 ↔ Part 4 integration and the allocator input **preview**. It does not verify real allocation callbacks, seat holds, payment, Redis crash recovery, or exactly-once delivery during failures.
