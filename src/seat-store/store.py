"""Authoritative seat transitions. Every mutation locks request, then section."""

from uuid import UUID, uuid4

from psycopg.types.json import Jsonb


class StoreError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def timestamp(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def validate_text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise StoreError("invalid_input", f"{field} must be a non-empty string up to 128 characters", 400)
    return value


class SeatStore:
    def __init__(self, database, hold_ttl=300):
        if type(hold_ttl) is not int or hold_ttl <= 0:
            raise ValueError("Hold duration must be a positive integer")
        self.db, self.hold_ttl = database, hold_ttl

    @staticmethod
    def _lock_request(conn, request_id):
        # Also serializes reuse of one request ID across different sections/processes.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                     ("seat-store-request:" + request_id,))

    @staticmethod
    def _lock_section(conn, section):
        row = conn.execute("SELECT section FROM sections WHERE section = %s FOR UPDATE",
                           (section,)).fetchone()
        if not row:
            raise StoreError("unknown_section", "Section does not exist", 404)

    @staticmethod
    def _seat_record(row):
        return {"seat_id": row["seat_id"], "section": row["section"], "row": row["row"],
                "position_in_row": row["position_in_row"], "state": row["state"],
                "held_by_request_id": row["request_id"],
                "hold_expiry": timestamp(row["hold_expiry"]),
                "hold_id": str(row["hold_id"]) if row["hold_id"] else None}

    def list_seats(self, section):
        validate_text(section, "section")
        with self.db.connect() as conn:
            if not conn.execute("SELECT 1 FROM sections WHERE section = %s", (section,)).fetchone():
                raise StoreError("unknown_section", "Section does not exist", 404)
            # One statement gives a consistent committed section snapshot.
            rows = conn.execute("""
                SELECT s.*, h.request_id, h.hold_id,
                       CASE WHEN s.state = 'HELD' THEN h.hold_expiry END AS hold_expiry
                FROM seats s LEFT JOIN holds h ON h.hold_id = s.current_hold_id
                WHERE s.section = %s ORDER BY s.row, s.position_in_row
            """, (section,)).fetchall()
            return [self._seat_record(row) for row in rows]

    def _result(self, conn, hold):
        # This is the outcome of this hold, not the current ownership of reused seats.
        state = {"ACTIVE": "HELD", "CONFIRMED": "CONFIRMED", "EXPIRED": "AVAILABLE"}[hold["status"]]
        rows = conn.execute("""
            SELECT s.seat_id, s.section, s.row, s.position_in_row
            FROM hold_seats hs JOIN seats s ON s.seat_id = hs.seat_id
            WHERE hs.hold_id = %s ORDER BY s.row, s.position_in_row
        """, (hold["hold_id"],)).fetchall()
        expiry = hold["hold_expiry"] if hold["status"] == "ACTIVE" else None
        records = [self._seat_record(dict(row, state=state,
                   request_id=hold["request_id"] if state != "AVAILABLE" else None,
                   hold_expiry=expiry,
                   hold_id=hold["hold_id"] if state != "AVAILABLE" else None)) for row in rows]
        return {"success": True, "request_id": hold["request_id"],
                "hold_id": str(hold["hold_id"]), "hold_status": hold["status"],
                "hold_expiry": timestamp(expiry), "seats": records}

    def hold(self, section, party_size, request_id, reoffer_key=None):
        validate_text(section, "section")
        validate_text(request_id, "request_id")
        if type(party_size) is not int or party_size not in (1, 2, 3, 4):
            raise StoreError("invalid_input", "party_size must be an integer from 1 to 4", 400)
        attempt_key = "initial"
        if reoffer_key is not None:
            attempt_key = "reoffer:" + validate_text(reoffer_key, "reoffer_key")
        with self.db.connect() as conn:
            self._lock_request(conn, request_id)
            self._lock_section(conn, section)
            previous = conn.execute(
                "SELECT * FROM holds WHERE request_id = %s ORDER BY created_at", (request_id,)
            ).fetchall()
            if any(h["section"] != section or h["party_size"] != party_size for h in previous):
                raise StoreError("request_conflict", "Request ID already has different booking details")
            same = next((h for h in previous if h["attempt_key"] == attempt_key), None)
            if same:
                if same["status"] == "EXPIRED" or (same["status"] == "ACTIVE" and
                        conn.execute("SELECT clock_timestamp() >= %s AS overdue",
                                     (same["hold_expiry"],)).fetchone()["overdue"]):
                    raise StoreError("hold_expired", "This attempt expired; use a new reoffer_key for a reoffer")
                return self._result(conn, same)
            if previous and any(h["status"] != "EXPIRED" for h in previous):
                raise StoreError("booking_exists", "Request already has an active or confirmed booking")
            if reoffer_key is not None and not previous:
                raise StoreError("invalid_reoffer", "A reoffer requires a previous expired hold")
            available = conn.execute("""
                SELECT seat_id, row, position_in_row FROM seats
                WHERE section = %s AND state = 'AVAILABLE' ORDER BY row, position_in_row
            """, (section,)).fetchall()
            block = []
            for seat in available:
                if block and (seat["row"] != block[-1]["row"] or
                              seat["position_in_row"] != block[-1]["position_in_row"] + 1):
                    block = []
                block.append(seat)
                if len(block) == party_size:
                    break
            if len(block) != party_size:
                return {"success": False}
            hold_id = uuid4()
            hold = conn.execute("""
                INSERT INTO holds(hold_id, request_id, attempt_key, section, party_size, status, hold_expiry)
                VALUES (%s, %s, %s, %s, %s, 'ACTIVE',
                        clock_timestamp() + %s * INTERVAL '1 second') RETURNING *
            """, (hold_id, request_id, attempt_key, section, party_size, self.hold_ttl)).fetchone()
            seat_ids = [s["seat_id"] for s in block]
            updated = conn.execute("""
                UPDATE seats SET state = 'HELD', current_hold_id = %s
                WHERE seat_id = ANY(%s) AND state = 'AVAILABLE'
            """, (hold_id, seat_ids)).rowcount
            if updated != party_size:
                raise RuntimeError("Seat ownership invariant violated")
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO hold_seats VALUES (%s, %s, %s)",
                                [(hold_id, seat_id, section) for seat_id in seat_ids])
            return self._result(conn, hold)

    def transition(self, request_id, action, hold_id=None):
        validate_text(request_id, "request_id")
        if action not in ("confirm", "expire"):
            raise ValueError("Unknown hold transition")
        if hold_id is not None:
            try:
                hold_id = UUID(str(hold_id))
            except (ValueError, TypeError, AttributeError):
                raise StoreError("invalid_input", "hold_id must be a UUID", 400) from None
        outcome_error = None
        with self.db.connect() as conn:
            self._lock_request(conn, request_id)
            history = conn.execute("SELECT * FROM holds WHERE request_id = %s ORDER BY created_at",
                                   (request_id,)).fetchall()
            if not history:
                raise StoreError("unknown_request", "Request has no hold", 404)
            if hold_id is None:
                if len(history) != 1:
                    raise StoreError("hold_id_required", "hold_id is required after a reoffer")
                hold = history[0]
            else:
                hold = next((h for h in history if h["hold_id"] == hold_id), None)
                if hold is None:
                    raise StoreError("unknown_hold", "Hold does not belong to this request", 404)
            self._lock_section(conn, hold["section"])
            if hold["status"] == "CONFIRMED":
                if action == "expire":
                    raise StoreError("already_confirmed", "Confirmed bookings cannot expire")
            elif hold["status"] == "EXPIRED":
                if action == "confirm":
                    raise StoreError("hold_expired", "Expired holds cannot be confirmed")
            else:
                # Use database wall time AFTER waiting for locks, not transaction start time.
                overdue = conn.execute("SELECT clock_timestamp() >= %s AS overdue",
                                       (hold["hold_expiry"],)).fetchone()["overdue"]
                if action == "expire" and not overdue:
                    raise StoreError("hold_not_due", "Hold deadline has not passed")
                if overdue:
                    hold = self._expire_locked(conn, hold)
                    if action == "confirm":
                        # Commit the release/outbox before returning a rejected late confirmation.
                        outcome_error = StoreError("hold_expired", "Payment deadline has passed")
                else:
                    hold = conn.execute("""
                        UPDATE holds SET status = 'CONFIRMED', confirmed_at = clock_timestamp()
                        WHERE hold_id = %s RETURNING *
                    """, (hold["hold_id"],)).fetchone()
                    changed = conn.execute("""
                        UPDATE seats SET state = 'CONFIRMED'
                        WHERE current_hold_id = %s AND state = 'HELD'
                    """, (hold["hold_id"],)).rowcount
                    if changed != hold["party_size"]:
                        raise RuntimeError("Partial party confirmation prevented")
            result = self._result(conn, hold)
        if outcome_error:
            raise outcome_error
        return result

    def _expire_locked(self, conn, hold):
        hold = conn.execute("""
            UPDATE holds SET status = 'EXPIRED', expired_at = clock_timestamp()
            WHERE hold_id = %s RETURNING *
        """, (hold["hold_id"],)).fetchone()
        released = conn.execute("""
            UPDATE seats SET state = 'AVAILABLE', current_hold_id = NULL
            WHERE current_hold_id = %s AND state = 'HELD' RETURNING seat_id, row, position_in_row
        """, (hold["hold_id"],)).fetchall()
        if len(released) != hold["party_size"]:
            raise RuntimeError("Partial party release prevented")
        event_id = uuid4()
        payload = {"event_id": str(event_id), "hold_id": str(hold["hold_id"]),
                   "request_id": hold["request_id"], "section": hold["section"],
                   "seats": [s["seat_id"] for s in sorted(
                       released, key=lambda s: (s["row"], s["position_in_row"]))],
                   "expired_at": timestamp(hold["expired_at"])}
        conn.execute("""
            INSERT INTO notification_outbox(event_id, hold_id, payload) VALUES (%s, %s, %s)
        """, (event_id, hold["hold_id"], Jsonb(payload)))
        return hold

    def expire_due(self, limit=100):
        with self.db.connect() as conn:
            due = conn.execute("""
                SELECT request_id, hold_id FROM holds
                WHERE status = 'ACTIVE' AND hold_expiry <= clock_timestamp()
                ORDER BY hold_expiry LIMIT %s
            """, (limit,)).fetchall()
        count = 0
        for hold in due:
            try:
                self.transition(hold["request_id"], "expire", hold["hold_id"])
                count += 1
            except StoreError as exc:
                if exc.code != "already_confirmed":
                    raise
        return count

