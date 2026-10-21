"""The foundation app must start without database configuration."""

from app import create_app


def test_health_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    with app.test_client() as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.is_json
    assert response.json == {"status": "ok"}
