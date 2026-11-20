-- Add a terminal cancellation state without changing existing bookings.
ALTER TABLE holds ADD COLUMN cancelled_at TIMESTAMPTZ;
ALTER TABLE holds DROP CONSTRAINT holds_status_check;
ALTER TABLE holds DROP CONSTRAINT holds_check;
ALTER TABLE holds ADD CONSTRAINT holds_status_check
    CHECK (status IN ('ACTIVE', 'CONFIRMED', 'EXPIRED', 'CANCELLED'));
ALTER TABLE holds ADD CONSTRAINT holds_check CHECK (
    (status = 'ACTIVE' AND confirmed_at IS NULL AND expired_at IS NULL AND cancelled_at IS NULL) OR
    (status = 'CONFIRMED' AND confirmed_at IS NOT NULL AND expired_at IS NULL AND cancelled_at IS NULL) OR
    (status = 'EXPIRED' AND expired_at IS NOT NULL AND confirmed_at IS NULL AND cancelled_at IS NULL) OR
    (status = 'CANCELLED' AND cancelled_at IS NOT NULL AND confirmed_at IS NULL AND expired_at IS NULL)
);

-- Existing installations gain D with the same layout as C. Fresh installations
-- have no sections yet and are populated by the normal seed operation.
INSERT INTO sections(section, row_count, seats_per_row)
    SELECT 'D', row_count, seats_per_row FROM sections WHERE section = 'C'
    ON CONFLICT (section) DO NOTHING;
INSERT INTO seats(seat_id, section, row, position_in_row)
    SELECT 'D-' || r || '-' || p, 'D', r, p
    FROM sections CROSS JOIN LATERAL generate_series(1, row_count) r
    CROSS JOIN LATERAL generate_series(1, seats_per_row) p
    WHERE section = 'D'
    ON CONFLICT (seat_id) DO NOTHING;
