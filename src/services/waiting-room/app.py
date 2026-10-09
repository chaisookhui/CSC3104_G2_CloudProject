
from flask import Flask, request, jsonify
from datetime import datetime, timezone
import uuid

app = Flask(__name__)

# Temporary waiting room storage
waiting_room = {
    "A": [],
    "B": [],
    "C": []
}

@app.route("/submit", methods=["POST"])
def submit_request():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    section = data.get("section")
    party_size = data.get("party_size")
    user_id = data.get("user_id")

    if section not in waiting_room:
        return jsonify({"error": "Invalid section"}), 400

    if type(party_size) is not int or not 1 <= party_size <= 4:
        return jsonify({"error": "Party size must be 1-4"}), 400

    if not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"error": "Invalid user ID"}), 400

    new_request = {
        "request_id": str(uuid.uuid4()),
        "user_id": user_id,
        "section": section,
        "party_size": party_size,
        "entry_type": "waiting_room",
        "batch_order": None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    waiting_room[section].append(new_request)

    return jsonify(new_request), 201


@app.route("/status", methods=["GET"])
def get_status():
    return jsonify({
        "waiting_count": sum(
            len(queue) for queue in waiting_room.values()
        ),
        "admission_state": "not_configured"
    })


if __name__ == "__main__":
    app.run(port=5001, debug=True)
