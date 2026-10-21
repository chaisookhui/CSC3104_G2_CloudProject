# WY: waitlist policy and mock-payment lifecycle

## Task goals

- [x] Preserve seat-store as the only seat/hold writer.
- [x] Add exact hold lookup for uncertain confirmation recovery.
- [x] Persist keyed mock-payment attempts before confirmation.
- [x] Recover committed confirmation after response loss; reject stale hold effects.
- [x] Persist/deduplicate expiry events before acknowledgement.
- [x] Implement largest-fitting initial queue heads and strict FCFS late-entry selection.
- [x] Validate the first slice against real PostgreSQL: 9 WY tests pass; the preceding full database run passed 52 tests, plus the root smoke test.
- [ ] Integrate durable waitlist membership, leave and preference changes with admission.
- [ ] Integrate offer-attempt persistence and section scheduling with Xin/Sook Hui/Linc.
- [ ] Add integrated process-crash, scheduling-priority and preference/offer race tests.

This is the first WY implementation slice, not a complete ticketing journey.
The policy follows the team's supplied technical reference defaults. Initial
requests preserve rank within party size; the largest fitting queue head wins.
Late/re-entry requests are eligible only when no initial head fits, with strict
arrival ordering and head-of-line blocking. `policy.select_next` receives eligible
entries for exactly one sale/section and the sizes that fit the current inventory.
It does not mutate seats, persist queues, or grant allocation authority.

Queued/waiting preference changes should supersede the old request and create a
new re-entry request. Active-offer changes are unsupported. Expired users explicitly
re-enter without original batch priority. These admission operations are not yet
implemented here. There is no offer-count limit.

## Run locally

Use the root Python 3.15.0 environment and existing PostgreSQL setup. This first
slice uses the existing configured application database, with separate `wy_*`
tables; it never writes seat-store tables. Seat-store remains on port 5003.
From the repository root:

```powershell
.\.venv\Scripts\python.exe src/waitlist-payment/service.py init-db
.\.venv\Scripts\python.exe src/waitlist-payment/service.py serve
# In another terminal:
.\.venv\Scripts\python.exe src/waitlist-payment/service.py worker
```

The API binds to 127.0.0.1:5004. Set `SEAT_STORE_URL` if needed. Both processes
load the existing seat-store `.env`. These are trusted local development endpoints,
without caller authentication; they are not public deployment interfaces.

After obtaining a seat-store hold, POST `/payments` with
`{request_id, hold_id, outcome, attempt_key}`. Outcomes are `success`, `decline`,
or `timeout`. The response contains `payment_id` and the current status. Poll
`GET /payments/{payment_id}`; the separate recovery worker processes intent.
Reuse the same attempt key and payload after network failure. Changed payload
under the same key returns 409. Only one pending attempt per hold is permitted.
A declined attempt permits a new key; retries never extend the seat-store deadline.
The timeout scenario simulates no definitive provider result: it stays pending
until hold expiry. No real provider or charge exists.

Payment status here is a booking reconciliation projection (`pending`, `failed`,
`confirmed`, `expired`), not proof of a financial settlement. The immutable mock
`outcome` records the simulation separately. Even a previously declined record
may project confirmed if another attempt confirms its hold.

Seat-store's new internal `GET /holds/{hold_id}?request_id=...` returns the existing
hold response shape. It reads committed state, does not expire holds on read, and
may report ACTIVE past deadline until a transition/scanner processes it. Confirmation
still checks database time after locks and is the authority for deadline decisions.

`POST /notify/expired` durably records the event before returning `success:true`.
Duplicate event IDs with changed payload conflict. Recovery checks the exact hold
before processing an event. Notifications never directly allocate replacement seats.
An old event cannot expire a newer hold. An unresolved dependency leaves work pending.

## Tests and integration boundaries

Run `.\test.ps1` from the root. WY tests live with seat-store tests to reuse their
real PostgreSQL fixture: each test gets an isolated disposable schema in `*_test`.
They exercise actual persistence and use a local seat-store adapter for lifecycle
calls; the hold lookup and expiry inbox HTTP routes are also tested. A simulated
response loss after committed confirmation verifies fresh-instance reconciliation.
This is not yet a real multi-process/network-partition end-to-end test.

The current inventory has no sale scoping. Do not mix sales. Xin's future scheduler
must serialize decisions per section, persist an offer attempt before a remote
hold call, and resolve uncertain attempts before selecting again. A seat lock alone
does not enforce queue priority. Atomic admission preference changes and scheduler
claims need owner integration; this module intentionally creates no competing allocator.
