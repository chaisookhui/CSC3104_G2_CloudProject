"""SeatStore HTTP adapter. SeatStore alone selects and writes adjacent seats."""
import os
import requests


class SeatStoreError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def hold_seats(section, party_size, request_id):
    """Reuse request_id on every delivery; never create a reoffer key here.

    Timeouts/503 may have committed: retry the identical request. A 409 requires
    reconciliation, not a new request ID or a fabricated no-seat result.
    """
    url = os.getenv("SEAT_STORE_URL", "http://127.0.0.1:5003").rstrip("/")
    try:
        response = requests.post(f"{url}/seats/hold", json={
            "section": section, "party_size": party_size, "request_id": request_id
        }, timeout=(3, 5))
        if response.status_code != 200:
            raise SeatStoreError(f"SeatStore HTTP {response.status_code}",
                                 retryable=response.status_code in (408, 429) or response.status_code >= 500)
        data = response.json()
        if not isinstance(data, dict) or type(data.get("success")) is not bool:
            raise SeatStoreError("Invalid SeatStore response")
        if data["success"] is False:
            return {"success": False}
        records = data.get("seats")
        if (data.get("request_id") != request_id or not isinstance(data.get("hold_id"), str)
                or not data["hold_id"] or data.get("hold_status") not in ("ACTIVE", "CONFIRMED")
                or not isinstance(data.get("hold_expiry"), str)
                or not isinstance(records, list) or len(records) != party_size):
            raise SeatStoreError("Incomplete or mismatched SeatStore hold")
        if any(not isinstance(s, dict) or not isinstance(s.get("seat_id"), str)
               or s.get("section") != section or type(s.get("row")) is not int
               or type(s.get("position_in_row")) is not int
               or s.get("held_by_request_id") != request_id or s.get("hold_id") != data["hold_id"]
               or s.get("state") != ("HELD" if data["hold_status"] == "ACTIVE" else "CONFIRMED")
               for s in records):
            raise SeatStoreError("Invalid seat ownership in SeatStore response")
        positions = sorted(s["position_in_row"] for s in records)
        if (len({s["seat_id"] for s in records}) != party_size or len({s["row"] for s in records}) != 1
                or positions != list(range(positions[0], positions[0] + party_size))):
            raise SeatStoreError("SeatStore returned nonadjacent or duplicate seats")
        return {"success": True, "request_id": request_id, "hold_id": data["hold_id"],
                "hold_status": data["hold_status"], "hold_expiry": data["hold_expiry"],
                "seats": [s["seat_id"] for s in records]}
    except (requests.RequestException, ValueError) as exc:
        raise SeatStoreError(f"SeatStore response uncertain: {type(exc).__name__}") from exc
