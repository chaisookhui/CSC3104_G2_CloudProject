
import os
import requests


# Module 4 URL (configurable for integration)
WAITLIST_URL = os.getenv(
    "WAITLIST_URL",
    "http://127.0.0.1:5004"
)


class WaitlistError(Exception):
    """Raised when Module 4 cannot process a request."""
    pass


def join_waitlist(ticket_request):
    """
    Send an unsuccessful ticket request to Module 4.

    Module 4 owns and manages the waitlist.
    Module 2 does not store waitlist entries directly.
    """

    payload = {
        **ticket_request,
        "reason": "temporarily_full"
    }

    try:
        response = requests.post(
            f"{WAITLIST_URL}/waitlist/join",
            json=payload,
            timeout=5
        )

        response.raise_for_status()
        data = response.json()

        # Validate the response
        if not isinstance(data, dict):
            raise WaitlistError("Invalid waitlist response")

        if data.get("request_id") != ticket_request["request_id"]:
            raise WaitlistError("Waitlist request ID mismatch")

        if data.get("status") != "waiting":
            raise WaitlistError("Request not added to waitlist")

        return data

    except (requests.RequestException, ValueError, KeyError) as error:
        raise WaitlistError(
            f"Waitlist communication failed: {error}"
        ) from error
