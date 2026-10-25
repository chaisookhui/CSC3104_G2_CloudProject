# Integration testing

The former in-memory mock runbook has been superseded by [README.md](README.md).
Use dispatcher port 5005, seat-store port 5003 and UUID batch IDs. Do not assume
batch-0001 or reset durable state to recover a timeout.

Run the regression and five-service PostgreSQL integration commands in that README.
The suite covers checkout discovery before batch completion, payment confirmation,
cancellation after response loss, expired/unavailable exit points, Section D and
PostgreSQL dispatcher restart after accepted submission. Dispatcher unit tests cover
lost claim/submission/outcome replies, lease fencing and duplicate event receipts.

For a live manual acceptance run, start seat-store with migration 002, payment API
and worker, initialized allocation API and worker, waiting room, and dispatcher
API/worker. Configure shared persistent storage and reachable service URLs. Submit
{user_id,section,party_size} to waiting-room /submit, POST /sale/start, poll
/requests/{request_id}/checkout, then use its exact hold_id for POST payment /payments.
For cancellation POST waiting-room /requests/{request_id}/cancel with {action_key},
poll checkout until cancelled. A cancelled, expired or UNAVAILABLE request ends
there: submitting again with the same user_id returns that finished entry.

Restart dispatcher while a batch is active; verify the same batch ID completes.
Let the queue empty, submit another user and verify periodic dispatch starts without
another sale/start call. Kill/restart workers and verify no overlapping seat ownership.
These manual container/network checks and load measurement are deployment acceptance,
not implied by passing routed HTTP integration tests.
