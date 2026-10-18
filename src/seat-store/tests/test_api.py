import pytest
from psycopg import OperationalError


def test_health_and_seat_record_contract(client):
    assert client.get("/health").json["storage"] == "postgresql"
    response = client.get("/seats/A")
    assert response.status_code == 200
    assert len(response.json) == 30
    assert response.json[0] == {
        "seat_id": "A-1-1", "section": "A", "row": 1, "position_in_row": 1,
        "state": "AVAILABLE", "held_by_request_id": None, "hold_expiry": None, "hold_id": None,
    }


def test_existing_allocator_wire_contract(client):
    response = client.post("/seats/hold", json={"section": "A", "party_size": 2, "request_id": "module2"})
    assert response.status_code == 200
    data = response.json
    assert data["success"] is True
    assert [s["seat_id"] for s in data["seats"]] == ["A-1-1", "A-1-2"]
    assert all(s["hold_expiry"] == data["hold_expiry"] for s in data["seats"])
    assert data["hold_expiry"].endswith("Z")
    confirmed = client.post("/seats/confirm", json={"request_id": "module2"})
    assert confirmed.status_code == 200
    assert confirmed.json["hold_status"] == "CONFIRMED"


@pytest.mark.parametrize("payload", [None, [], {}, {"section": "A"},
    {"section": "A", "party_size": True, "request_id": "x"},
    {"section": "A", "party_size": 0, "request_id": "x"},
    {"section": "A", "party_size": 5, "request_id": "x"},
    {"section": "A", "party_size": 2.0, "request_id": "x"},
    {"section": "A", "party_size": 1, "request_id": " "},
    {"section": "A", "party_size": 1, "request_id": "x", "surprise": True},
    {"section": "A", "party_size": 1, "request_id": "x", "reoffer_key": None},
])
def test_invalid_hold_inputs(client, payload):
    response = client.post("/seats/hold", json=payload)
    assert response.status_code == 400
    assert response.json["error"] == "invalid_input"


def test_unknown_section_and_request(client):
    assert client.get("/seats/Z").status_code == 404
    assert client.post("/seats/hold", json={"section": "Z", "party_size": 1, "request_id": "x"}).status_code == 404
    assert client.post("/seats/confirm", json={"request_id": "missing"}).status_code == 404
    assert client.post("/seats/expire", json={"request_id": "missing", "hold_id": "bad"}).status_code == 400


def test_expiry_endpoint_only_releases_due_holds(client, store, make_due):
    booking = store.hold("A", 2, "expiry-api")
    assert client.post("/seats/expire", json={"request_id": "expiry-api"}).status_code == 409
    make_due(booking["hold_id"])
    result = client.post("/seats/expire", json={"request_id": "expiry-api", "hold_id": booking["hold_id"]})
    assert result.status_code == 200
    assert result.json["hold_status"] == "EXPIRED"


def test_storage_failure_is_503_and_never_no_seats(client, db, monkeypatch):
    def unavailable():
        raise OperationalError("simulated partition")
    monkeypatch.setattr(db, "connect", unavailable)
    result = client.post("/seats/hold", json={"section": "A", "party_size": 2, "request_id": "network"})
    assert result.status_code == 503
    assert result.json["error"] == "storage_unavailable"
    assert "success" not in result.json
    assert client.get("/health").status_code == 503


def test_http_errors_are_json(client):
    assert client.get("/missing").is_json
    assert client.get("/seats/hold").status_code == 404  # GET treats hold as a section name.
    response = client.post("/seats/hold", data="{" , content_type="application/json")
    assert response.status_code == 400 and response.is_json
    assert client.post("/seats/hold", data="x" * 20000,
                       content_type="application/json").status_code == 413

