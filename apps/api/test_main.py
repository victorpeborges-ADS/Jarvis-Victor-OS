import hashlib
import hmac

from fastapi.testclient import TestClient
from main import create_app
from server_config import LocalServerConfig

client = TestClient(create_app(LocalServerConfig()), base_url="http://127.0.0.1", client=("127.0.0.1", 51000))

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["demo"] is True
    assert "x-jarvis-e2e-ready-proof" not in r.headers

def test_e2e_health_proof_is_a_keyed_challenge(monkeypatch, tmp_path):
    token = "synthetic-runner-private-random-token"
    monkeypatch.setenv("JARVIS_E2E_READY_TOKEN", token)
    app = create_app(LocalServerConfig(), database_path=tmp_path / "e2e-health.sqlite3")
    test_client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51001))
    nonce = "ab" * 32
    response = test_client.get("/health", headers={"x-jarvis-e2e-nonce": nonce})
    assert response.status_code == 200
    assert response.headers["x-jarvis-e2e-ready-proof"] == hmac.new(
        token.encode("ascii"), nonce.encode("ascii"), hashlib.sha256
    ).hexdigest()
    assert "x-jarvis-e2e-ready-proof" not in test_client.get(
        "/health", headers={"x-jarvis-e2e-nonce": "invalid"}
    ).headers

def test_briefing_has_next():
    r = client.get("/briefing")
    assert r.status_code == 200
    assert "next_commitment" in r.json()

def test_events_demo():
    r = client.get("/events")
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 3
    by_id = {e["id"]: e for e in events}
    mentioned = by_id["evt_006"]
    assert "CRIVO" in mentioned["title"]
    assert mentioned["domain_id"] == "dom_medsyn"
    assert all(e.get("domain_id") != "dom_crivo" or "CRIVO" not in e["title"] or e["id"] != "evt_006" for e in events)

def test_unknown_domain_present_but_not_a_known_filter():
    r = client.get("/domains")
    ids = {d["id"] for d in r.json()}
    assert len(ids) == 8
    events = client.get("/events").json()
    unknown = [e for e in events if e.get("domain_id") not in ids]
    assert any(e["id"] == "evt_011" for e in unknown)
    assert any(e["id"] == "evt_012" for e in unknown)
    assert "dom_fantasma" not in ids

def test_sources_stale_visible():
    r = client.get("/sources")
    data = r.json()
    assert any(s["sync_status"] == "stale" for s in data)
