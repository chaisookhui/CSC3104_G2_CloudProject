ALTER TABLE wy_payments ADD COLUMN attempt_status TEXT;
ALTER TABLE wy_payments DROP CONSTRAINT wy_payments_status_check;
ALTER TABLE wy_payments ADD CONSTRAINT wy_payments_status_check
    CHECK (status IN ('pending','confirmed','failed','expired','cancelled'));
UPDATE wy_payments SET attempt_status = CASE
    WHEN outcome = 'decline' THEN 'declined'
    WHEN status = 'confirmed' AND outcome = 'success' THEN 'succeeded'
    WHEN status IN ('confirmed', 'expired') THEN 'closed'
    ELSE 'pending' END;
ALTER TABLE wy_payments ALTER COLUMN attempt_status SET NOT NULL;
ALTER TABLE wy_payments ADD CONSTRAINT wy_attempt_status
    CHECK (attempt_status IN ('pending','succeeded','declined','closed'));
-- Keep the legacy status a booking projection, with failed for an active declined attempt.
-- Confirmed legacy rows are historical facts; pending uniqueness is independent of it.
CREATE UNIQUE INDEX wy_one_pending_attempt ON wy_payments(hold_id) WHERE attempt_status='pending';

CREATE TABLE wy_checkouts (
    hold_id UUID PRIMARY KEY,
    request_id TEXT NOT NULL,
    hold_status TEXT NOT NULL CHECK (hold_status IN ('ACTIVE','CONFIRMED','EXPIRED','CANCELLED')),
    snapshot JSONB NOT NULL,
    original_expiry TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX wy_checkout_request ON wy_checkouts(request_id);
CREATE TABLE wy_cancellations (
    action_id UUID PRIMARY KEY,
    hold_id UUID NOT NULL,
    request_id TEXT NOT NULL,
    action_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','cancelled','expired','confirmed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(hold_id, action_key),
    UNIQUE(hold_id)
);
CREATE TABLE wy_work (
    work_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('payment','cancel','event','checkout','notification')),
    payload JSONB NOT NULL,
    state TEXT NOT NULL DEFAULT 'READY' CHECK (state IN ('READY','IN_PROGRESS','DONE','BLOCKED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    token UUID,
    lease_until TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX wy_work_ready ON wy_work(state, available_at);
CREATE TABLE wy_notifications (
    event_id UUID PRIMARY KEY,
    payload JSONB NOT NULL,
    delivered_at TIMESTAMPTZ
);
CREATE INDEX wy_expiry_unprocessed ON wy_expiry_events(created_at) WHERE processed_at IS NULL;

-- Backfill legacy work without deleting history or touching inventory tables.
INSERT INTO wy_work(work_id,kind,payload)
SELECT 'payment:'||payment_id, 'payment', jsonb_build_object('payment_id',payment_id)
FROM wy_payments WHERE attempt_status='pending';
INSERT INTO wy_work(work_id,kind,payload)
SELECT 'checkout:'||hold_id, 'checkout', jsonb_build_object('request_id',request_id,'hold_id',hold_id)
FROM wy_payments WHERE status IN ('pending','failed') ON CONFLICT DO NOTHING;
INSERT INTO wy_work(work_id,kind,payload)
SELECT 'event:'||event_id, 'event', jsonb_build_object('event_id',event_id)
FROM wy_expiry_events WHERE processed_at IS NULL;
