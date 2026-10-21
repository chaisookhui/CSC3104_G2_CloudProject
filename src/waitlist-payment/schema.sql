CREATE TABLE IF NOT EXISTS wy_payments (
    payment_id UUID PRIMARY KEY,
    hold_id UUID NOT NULL,
    attempt_key TEXT NOT NULL,
    request_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'decline', 'timeout')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'failed', 'expired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (hold_id, attempt_key)
);
CREATE TABLE IF NOT EXISTS wy_expiry_events (
    event_id UUID PRIMARY KEY,
    hold_id UUID NOT NULL,
    request_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
