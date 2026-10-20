CREATE TABLE sections (
    section TEXT PRIMARY KEY,
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    seats_per_row INTEGER NOT NULL CHECK (seats_per_row = 10)
);

CREATE TABLE holds (
    hold_id UUID PRIMARY KEY,
    request_id TEXT NOT NULL CHECK (length(request_id) BETWEEN 1 AND 128),
    attempt_key TEXT NOT NULL,
    section TEXT NOT NULL REFERENCES sections(section),
    party_size INTEGER NOT NULL CHECK (party_size BETWEEN 1 AND 4),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'CONFIRMED', 'EXPIRED')),
    hold_expiry TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    confirmed_at TIMESTAMPTZ,
    expired_at TIMESTAMPTZ,
    UNIQUE (request_id, attempt_key),
    UNIQUE (hold_id, section),
    CHECK (
        (status = 'ACTIVE' AND confirmed_at IS NULL AND expired_at IS NULL) OR
        (status = 'CONFIRMED' AND confirmed_at IS NOT NULL AND expired_at IS NULL) OR
        (status = 'EXPIRED' AND expired_at IS NOT NULL AND confirmed_at IS NULL)
    )
);
CREATE UNIQUE INDEX one_live_booking_per_request
    ON holds(request_id) WHERE status IN ('ACTIVE', 'CONFIRMED');
CREATE INDEX overdue_holds ON holds(hold_expiry) WHERE status = 'ACTIVE';

CREATE TABLE seats (
    seat_id TEXT PRIMARY KEY,
    section TEXT NOT NULL REFERENCES sections(section),
    row INTEGER NOT NULL CHECK (row > 0),
    position_in_row INTEGER NOT NULL CHECK (position_in_row BETWEEN 1 AND 10),
    state TEXT NOT NULL DEFAULT 'AVAILABLE'
        CHECK (state IN ('AVAILABLE', 'HELD', 'CONFIRMED')),
    current_hold_id UUID,
    UNIQUE (section, row, position_in_row),
    UNIQUE (seat_id, section),
    FOREIGN KEY (current_hold_id, section) REFERENCES holds(hold_id, section),
    CHECK ((state = 'AVAILABLE' AND current_hold_id IS NULL) OR
           (state IN ('HELD', 'CONFIRMED') AND current_hold_id IS NOT NULL))
);
CREATE INDEX available_seats ON seats(section, row, position_in_row)
    WHERE state = 'AVAILABLE';

CREATE TABLE hold_seats (
    hold_id UUID NOT NULL,
    seat_id TEXT NOT NULL,
    section TEXT NOT NULL,
    PRIMARY KEY (hold_id, seat_id),
    FOREIGN KEY (hold_id, section) REFERENCES holds(hold_id, section),
    FOREIGN KEY (seat_id, section) REFERENCES seats(seat_id, section)
);

CREATE TABLE notification_outbox (
    event_id UUID PRIMARY KEY,
    hold_id UUID NOT NULL UNIQUE REFERENCES holds(hold_id),
    payload JSONB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    lease_until TIMESTAMPTZ,
    lease_token UUID,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX pending_notifications ON notification_outbox(next_attempt_at)
    WHERE delivered_at IS NULL;

