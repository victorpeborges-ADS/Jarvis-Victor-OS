from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["demo"] is True

def test_briefing_has_next():
    r = client.get("/briefing")
    assert r.status_code == 200
    assert "next_commitment" in r.json()

def test_events_demo():
    r = client.get("/events")
    assert r.status_code == 200
    assert len(r.json()) >= 3

def test_sources_stale_visible():
    r = client.get("/sources")
    data = r.json()
    assert any(s["sync_status"] == "stale" for s in data)
