
import os
import requests


# Module 3 URL (can be changed when integrating)
SEAT_STORE_URL = os.getenv(
    "SEAT_STORE_URL",
    "http://127.0.0.1:5003"
)


class SeatStoreError(Exception):
    """Raised when Module 3 cannot be reached or responds incorrectly."""
    pass


def hold_seats(section, party_size, request_id):
    """
    Request Module 3 to hold seats.

    Returns:
        {
            "success": True,
            "seats": [...],
            "hold_expiry": "..."
        }

    Returns {"success": False} if no fitting seats exist.
    Raises SeatStoreError for communication failures.
    """

    payload = {
        "section": section,
        "party_size": party_size,
        "request_id": request_id
    }

    try:
        response = requests.post(
            f"{SEAT_STORE_URL}/seats/hold",
            json=payload,
            timeout=5
        )

        response.raise_for_status()
        data = response.json()

        # No fitting adjacent seats
        if data.get("success") is False:
            return {"success": False}

        # Real Module 3 may return seat records.
        # Normalise records to the format used by Module 2.
        if not isinstance(data, dict):
            raise SeatStoreError("Invalid Seat Store response")

        records = data.get("seats")

        if not isinstance(records, list):
            raise SeatStoreError("Missing seat records")

        seat_ids = []
        expiry = None

        for record in records:
            if not isinstance(record, dict):
                raise SeatStoreError("Invalid seat record")

            seat_ids.append(record["seat_id"])

            if expiry is None:
                expiry = record.get("hold_expiry")

        return {
            "success": True,
            "seats": seat_ids,
            "hold_expiry": expiry
        }

    except (requests.RequestException, ValueError, KeyError) as error:
        raise SeatStoreError(
            f"Seat Store communication failed: {error}"
        ) from error
