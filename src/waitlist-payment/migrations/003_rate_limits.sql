-- Three bounded service-wide buckets, shared by all payment API replicas.
CREATE TABLE wy_rate_limits (
    scope TEXT PRIMARY KEY CHECK (scope IN ('read', 'write', 'event')),
    window_id BIGINT NOT NULL,
    requests INTEGER NOT NULL CHECK (requests > 0)
);
