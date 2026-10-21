
from flask import Flask, request, jsonify

from algorithm import allocate_section
from seat_client import hold_seats, SeatStoreError
from waitlist_client import join_waitlist, WaitlistError


app = Flask(__name__)


@app.route("/allocate/<section>", methods=["POST"])
def allocate(section):
    """
    Allocate seats using the Demand-Cycle Algorithm.

    Successful requests receive held seats.
    Unsuccessful requests automatically join Module 4's waitlist.
    """

    requests_data = request.get_json(silent=True)

    # Validate incoming JSON
    if not isinstance(requests_data, list):
        return jsonify({
            "error": "Expected a list of requests"
        }), 400

    # Validate section
    if section not in ("A", "B", "C"):
        return jsonify({
            "error": "Invalid section"
        }), 400

    # Validate each request
    for item in requests_data:
        if (
            not isinstance(item, dict)
            or item.get("section") != section
            or type(item.get("party_size")) is not int
            or item["party_size"] not in (1, 2, 3, 4)
            or not isinstance(item.get("request_id"), str)
            or not item["request_id"]
        ):
            return jsonify({
                "error": "Invalid request data"
            }), 400

    # Reject duplicate request IDs within the same batch
    request_ids = [
        item["request_id"] for item in requests_data
    ]

    if len(request_ids) != len(set(request_ids)):
        return jsonify({
            "error": "Duplicate request IDs in batch"
        }), 400

    try:
        # Step 1: Run the allocation algorithm
        results = allocate_section(
            section,
            requests_data,
            hold_seats=hold_seats
        )

        # Step 2: Look up original request details
        requests_lookup = {
            item["request_id"]: item
            for item in requests_data
        }

        # Step 3: Send unsuccessful requests to Module 4
        for result in results:

            if result["outcome"] == "temporarily_full":

                original_request = requests_lookup[
                    result["request_id"]
                ]

                join_waitlist(original_request)

        # Step 4: Return allocation results
        return jsonify(results), 200

    except SeatStoreError as error:
        app.logger.error(
            "Seat Store error: %s", error
        )

        return jsonify({
            "error": "Seat Store unavailable",
            "message": "Allocation could not be completed"
        }), 503

    except WaitlistError as error:
        app.logger.error(
            "Waitlist error: %s", error
        )

        return jsonify({
            "error": "Waitlist service unavailable",
            "message": "Waitlist processing could not be completed"
        }), 503


if __name__ == "__main__":
    app.run(port=5002, debug=True)
