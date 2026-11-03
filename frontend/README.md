# Demo frontend

A plain HTML/CSS/JS page that walks through the booking flow for demos.
`server.py` serves the page and forwards `/api/<service>/<path>` to the backend
services, so the browser never calls the service ports directly (no CORS issues)
and the payment token stays on the server.

| Prefix | Service | Default address (env var) |
| --- | --- | --- |
| `/api/waiting-room/` | Waiting room | `http://127.0.0.1:5001` (`WAITING_ROOM_URL`) |
| `/api/allocation/` | Allocation | `http://127.0.0.1:5002` (`ALLOCATION_URL`) |
| `/api/seats/` | Seat-store | `http://127.0.0.1:5003` (`SEAT_STORE_URL`) |
| `/api/payment/` | Payment | `http://127.0.0.1:5004` (`PAYMENT_URL`) |
| `/api/dispatcher/` | Batch dispatcher | `http://127.0.0.1:5005` (`DISPATCHER_URL`) |

Set `PAYMENT_API_TOKEN` if the payment service requires it.

## Run

From the repository root, start Docker Desktop and run:

```powershell
python demo.py
```

This is the main project launcher. It starts frontend, all five service APIs,
their workers, PostgreSQL and Redis using `compose.core.yaml`. It generates ignored
`.env.core` credentials on first use and preserves data on subsequent runs.
Open http://127.0.0.1:18080. Stop with `python demo.py --stop`.
See [the full-stack runbook](../CONTAINERS.md) for networking, configuration,
health checks and the isolated full-network booking test. The standalone
`compose.frontend.yaml` remains available for frontend-only development.

The dev seat map has 70 seats. Use `python demo.py --batch-size 10` for a small
batch demonstration. Confirmed seats remain booked between runs; startup never
resets reservations or deletes dispatcher progress.

For native frontend-only development with separately running backends:

```powershell
python frontend/server.py
```

That standalone process uses port 8080 by default; the main container stack uses
host port 18080. Set the documented backend environment variables as needed.

## Demo users

- **Your name** (User > My booking) is the only sign-in. There is no account service,
  so the page creates a unique `user_id` and keeps it in this browser.
- **Register** (User > My booking) registers for the sale with a section and party size
  (waiting room `/submit`, status REGISTERED), matching the waiting-room slides.
- **More real users:** open another browser or a private window; each keeps its
  own user. "Switch user" in the header starts over in the same window.
- **Simulated users:** Admin > Overview > Simulate users registers many `sim-...` users
  through the same `/submit` endpoint, with a fixed or random section and party size.
  Add them before starting the sale; ones added afterwards join as latecomers.

## Tabs

The tab bar is grouped by who uses each tab. For demos, keep an Admin tab in one
window and User > My booking in another, side by side.

| Side | Tab / part | File | Status |
| --- | --- | --- | --- |
| Admin | Overview (simulate users, start sale, queue with batch and latecomer tags) | `admin.js` | Done |
| Admin | Batches (allocator demand cycle per section) | `batches.js` | Done |
| Admin | Seat map (seats per section filling up live) | `seats.js` | Implemented |
| User | My booking (your name, register, then live status) | `join.js`, `booking.js` | Done |
| User | Checkout, inside My booking below the status | `checkout.js` | Implemented |

**Checkout** is implemented in the `#checkout-step` container at the bottom of My booking,
shown once the request is RESERVED (`getCurrentRequest().allocation` has the
`hold_id`, seats and `hold_expiry`). The booking status stops refreshing at RESERVED,
and checkout polls payment/cancellation operations. Authoritative expiry refresh remains follow-up work. Existing endpoints: waiting room
`GET /requests/<id>/checkout` (booking status from payment) and
`POST /requests/<id>/cancel` (`{action_key}`); payment `POST /payments`
(`{request_id, hold_id, outcome, attempt_key}`) and `GET /payments/<id>`. Reuse
the same `attempt_key` when Pay is retried so a double click does not create a
second payment.

**Batches** reads dispatcher `/status` for the batches and allocation
`/batches/<id>` for each job's `priority` (turn order), `state` and seats, plus
`size_order` (rank). Demand counts come from the dispatcher's `section_demand`.
A new round starts when a party size comes up again in the turn order.

## Adding a tab or part

1. Fill in the placeholder in `static/index.html` (the Seat map `<section>`, or
   `#checkout-step` inside My booking) and add its `<script>` tag after `batches.js`.
2. Call services with `api(path)` for GET or `api(path, body)` for POST,
   e.g. `await api("seats/seats/A")`. It throws with the service's error message.
3. `getCurrentUser()` returns `{ name, user_id }`, or `null` before registering.
   `getCurrentRequest()` returns the latest waiting-room record for this browser:
   `request_id`, `user_id`, `section`, `party_size`, `status` and, once seats are
   held, `allocation` (`hold_id`, `hold_status`, `hold_expiry`, `seats`).
4. `onTabOpen("seats", fn)` runs `fn` each time the tab is shown (My booking's tab
   id is `join`).
5. Use `esc()` for any text placed into HTML, `message()` for notices,
   `badge(status)` for statuses, and the colour variables in `style.css`.
   `dispatchedBatches(dispatcherStatus)` lists batches in order, so "Batch N"
   matches the Overview and Batches tabs.
