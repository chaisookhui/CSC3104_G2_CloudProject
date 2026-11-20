# Payment reliability: implementation and evidence

This service is a mock checkout/payment orchestrator. It never captures money,
stores card details, refunds payments, or independently writes seat-store inventory.
Existing internal API shapes and module paths are retained for teammate integration.

## Review of the eight areas

| Area | Implemented here | Evidence / remaining boundary |
| --- | --- | --- |
| Idempotency | Unique hold/attempt key, input-conflict rejection, one pending attempt per hold, exact-hold retries | Duplicate burst through real Waitress, concurrent different keys, response-loss tests. No external charge guarantee. |
| Booking consistency | Seat-store owns atomic confirmation/expiry/cancellation; payment's terminal projection cannot regress | Seat-store race tests and five-service PostgreSQL integration; no shared cross-service transaction. |
| Fault tolerance | Durable jobs, 30-second claims, token fencing, reconciliation, bounded failures and jitter | Stale-claim, live response-loss and abrupt payment-process-exit tests. BLOCKED work requires repair. |
| High traffic | Waitress bounds, bounded connection pool, shared read/write/event quotas, atomic pending-attempt cap | Multi-process quota and concurrent admission tests. No 10,000-user capacity result; DB/seat-store remain dependencies. |
| Security | Internal token, separate signed checkout grants, exact-resource checks, strict payloads, optional TLS-only gateway | Cross-reservation/read-only/expired/tampered token tests. Trusted customer login and grant delivery are upstream responsibilities. |
| Deadline | Original seat-store hold deadline; database-time admission check; seat-store decides after locks | Retry, queued-expiry and confirmation/expiry race tests. Backlog and token lifetime never extend the reservation. |
| Durability | Attempt, processing tasks and business audit commit together; durable inbox/outbox and event deduplication | Abrupt exit, audit rollback, duplicate/conflicting/late event and dispatcher restart tests. Storage HA/backups must be provisioned. |
| Observability | Authenticated Prometheus endpoint, latency/counts, pending age, work state/failures/executions, abandoned claims, worker heartbeat, durable business audit | Metrics/auth/redaction and audit tests. A collector, dashboards and alert delivery still need deployment. |

The backend does not currently define ticket prices or currency. Amount, price,
card and outcome fields are rejected by the customer payment endpoint. It derives
the exact request/hold from a signed grant and uses a server-configured MOCK outcome.
Do not invent client-controlled amounts or claim real payment verification,
tokenisation, PCI compliance, provider callback verification, or financial compensation.

## Module organisation

| File | Responsibility |
| --- | --- |
| service.py | Existing internal HTTP adapter, API authentication, metrics hooks and CLI |
| lifecycle.py | Payment/cancellation orchestration, persistence, recovery and seat-store adapter |
| payment_db.py | Bounded per-process connection pooling and transaction contexts |
| payment_security.py | Optional signed checkout grants and customer-only HTTP adapter |
| payment_traffic.py | Shared database-clock fixed-window quotas |
| payment_retry.py | Bounded retry jitter |
| payment_audit.py | Allowlisted transactional business audit writes |
| payment_monitoring.py | Low-cardinality HTTP metrics and shared recovery observations |
| payment_serialization.py | JSON-safe public values shared by both HTTP adapters |
| migrations/ | Additive, checksummed payment-owned schema upgrades |

## Customer boundary: reservation-scoped bearer grants

Set PAYMENT_CHECKOUT_SIGNING_KEY to an independent random secret of at least 32
characters. It must differ from PAYMENT_API_TOKEN. Keep it in the payment Secret,
not in browser code, logs, source control or a URL. Without it, customer endpoints
are disabled. Existing trusted internal calls continue using PAYMENT_API_TOKEN.

A trusted operator/gateway issues a grant only AFTER authenticating the customer
and verifying that the customer owns the admission request. There is no public
minting endpoint, and supplying an arbitrary user_id is not identity verification.
The CLI verifies the real request/hold binding with seat-store, but cannot establish
who a human is. Use opaque subject identifiers, not names or email addresses.

```powershell
# Supply secrets through ignored configuration/environment, not command arguments.
.\src\waitlist-payment\run.ps1 -Command issue-checkout-token `
    -Subject 'customer-opaque-id' -RequestId 'original-request-id' `
    -HoldId 'original-hold-uuid' -Ttl 900 -Scopes 'read,pay,cancel'
```

The command intentionally writes a sensitive bearer token to stdout for secure
handoff. Do not paste it into shared terminals/reports. A trusted gateway may use
CheckoutTokens.issue after the same ownership checks. Grants are HMAC-SHA256 signed
with a fixed audience, exact request/hold, subject, allowed actions and a maximum
900-second lifetime. They are capabilities, not an account/session system. They
are not encrypted; possession permits the granted actions until expiry. Individual
revocation is not implemented; rotate the signing key to invalidate all grants.

Customers send `Authorization: Bearer <checkout-token>` over HTTPS:

| Route | Required scope | JSON / behaviour |
| --- | --- | --- |
| GET /customer/checkout | read | Uses only the token's request and hold |
| POST /customer/payments | pay | `{ "attempt_key": "stable-key-for-this-attempt" }` |
| GET /customer/payments/{id} | read | Verifies the saved attempt belongs to the token's request AND hold |
| POST /customer/cancel | cancel | `{ "action_key": "stable-key-for-this-cancellation" }` |
| GET /customer/cancellations/{id} | read | Verifies the saved cancellation's request AND hold |

Unknown body fields are rejected. Customers cannot choose another hold, price,
card data or simulated result. PAYMENT_CUSTOMER_MOCK_OUTCOME sets the simulator
result server-side (success/decline/timeout; default success). Keep it consistent
across API replicas. A service token cannot act as a customer token, and a customer
token cannot access internal APIs, callbacks or metrics.

## TLS gateway and scaling resources

compose.gateway.yaml is an OPTIONAL overlay, exposing only /customer/ on loopback
HTTPS port 5443. Provide a trusted certificate with a matching hostname in
PAYMENT_TLS_DIR/tls.crt and tls.key. The Nginx configuration permits TLS 1.2/1.3,
bounds request sizes/connections/timeouts, limits per-IP request rate, disables
automatic upstream retries, and keeps internal APIs/metrics outside this listener.
It does not make the waiting-room or other project APIs safe for public access.

```powershell
docker compose -f src/waitlist-payment/compose.yaml `
    -f src/waitlist-payment/compose.gateway.yaml config --quiet
docker compose -f src/waitlist-payment/compose.yaml `
    -f src/waitlist-payment/compose.gateway.yaml up -d api worker gateway
```

Use an image digest and your deployment's certificate/renewal policy before a
public rollout. Internal HTTP traffic still requires a restricted network or
separate transport security. Do not expose raw port 5004 or teammates' internal
APIs as customer endpoints. No real certificates/domain or running gateway are
provisioned by these source changes.

deploy/autoscaling.yaml optionally adds CPU-based API HPA (2-4 replicas, target
70% of requested CPU), requiring metrics-server and the existing API CPU request.
Workers scale separately. PostgreSQL backlog gauges are not automatically wired
to HPA, and CPU alone may miss an I/O bottleneck. Budget pool connections across
ALL replicas and measure database/seat-store pressure before increasing workers.
No cluster deployment, failover/HA or high-traffic throughput is claimed.

## Monitoring and audit operations

```powershell
.\src\waitlist-payment\run.ps1 -Command monitor
.\src\waitlist-payment\run.ps1 -Command work-status
```

GET /metrics uses the internal service token and bypasses business quotas.
HTTP counters, latency sum/count and maximum are per process and reset on restart;
scrape every API replica. Labels use fixed route names/status codes, never hold IDs,
request paths, subject names, bearer credentials or attempt keys. Shared work gauges
come from PostgreSQL: use MAX rather than SUM across replicas for the same shared
database, to avoid multiplying backlog counts. Failure/execution totals here are
gauges over CURRENT unfinished work, not monotonically increasing counters.

The heartbeat records the most recent recovery pass from ANY worker; it does not
prove every replica is alive or that every job is making progress. Suggested alerts:

- Worker heartbeat absent/stale while processing is expected (e.g. >120 seconds).
- BLOCKED work, abandoned claims, or increasing age of unresolved attempts.
- Sustained 429/503 responses, request latency or pool saturation.
- Unsent notifications when a consumer is expected; an intentionally unset
  PAYMENT_STATUS_URL is a known configuration state, not proof of lost bookings.

wy_audit records accepted payments/cancellations, first observations of checkout
states, unique incoming events, blocked work, explicit operator retries and CLI
grant issuance. Entries are committed with the associated state change. Replaying
an accepted attempt/event does not duplicate that business audit record. The
authenticated grant subject identifies customer-originated actions; internal calls
are attributed to the service role, not a claimed human. Raw request bodies,
attempt/action keys, bearer tokens, signing keys and card data are never audited.
This is an append-only application writer, not a cryptographically immutable ledger.

Apply migrations 003 and 004 with `init-db` before serving. Provision a runtime role
with SELECT/INSERT/UPDATE on operational wy_* tables, SELECT on migration metadata,
and INSERT only on wy_audit (grant audit reading separately to an operator role).
Do not grant routine audit UPDATE/DELETE or seat-store write privileges. Existing
owner-role local demos cannot enforce those role boundaries by themselves.

## Validation boundary

Run suites in separate Python processes as documented in README.md. Tests use
disposable PostgreSQL schemas and preserve development bookings. Reliability tests
include scoped ownership/scope/tamper checks, audit rollback and redaction, pending
admission concurrency, retry jitter, expired queued holds, late conflicting events,
metrics and an abrupt process exit after accepting a payment. Five-service tests
exercise scoped checkout against the actual seat-store implementation.

Source/configuration validation is separate from a successful Docker build, TLS
handshake, cluster recovery experiment, backup restoration or load benchmark.
