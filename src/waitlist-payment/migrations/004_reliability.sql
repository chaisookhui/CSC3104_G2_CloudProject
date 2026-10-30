CREATE TABLE wy_audit (
    audit_id UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    request_id TEXT,
    hold_id UUID,
    entity_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX wy_audit_hold ON wy_audit(hold_id, occurred_at);
CREATE TABLE wy_worker_health (
    id INTEGER PRIMARY KEY CHECK (id=1),
    worker_id UUID NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX wy_pending_attempts ON wy_payments(created_at) WHERE attempt_status='pending';
