import json
from pathlib import Path

import jsonschema
from fastapi.testclient import TestClient

import contract
from main import create_app
from server_config import LocalServerConfig

client = TestClient(create_app(LocalServerConfig()), base_url="http://127.0.0.1", client=("127.0.0.1", 51000))


def test_fixture_matches_canonical_schema():
    schema = json.loads(contract.SCHEMA.read_text())
    data = json.loads(contract.FIXTURES.read_text())
    jsonschema.Draft7Validator(schema).validate(data)


def test_medsyn_title_mentioning_crivo_keeps_its_domain():
    events = client.get("/events").json()
    mentioned = next(event for event in events if event["id"] == "evt_006")
    assert "CRIVO" in mentioned["title"]
    assert mentioned["domain_id"] == "dom_medsyn"


def test_invalid_event_is_quarantined_without_failing_the_response(tmp_path, monkeypatch):
    data = json.loads(contract.FIXTURES.read_text())
    valid = next(event for event in data["events"] if event["id"] == "evt_001")
    data["events"] = [None, "texto", {"id": "evt_bad", "domain_id": "dom_crivo"}, valid]
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(contract, "FIXTURES", path)
    response = client.get("/events")
    assert response.status_code == 200
    ids = [event["id"] for event in response.json()]
    assert ids == ["evt_001"]


def test_malformed_fixture_returns_422(tmp_path, monkeypatch):
    path = tmp_path / "demo.json"
    path.write_text("{não-json", encoding="utf-8")
    monkeypatch.setattr(contract, "FIXTURES", path)
    response = client.get("/events")
    assert response.status_code == 422


def test_frontend_and_backend_share_the_same_schema_file():
    assert contract.SCHEMA == Path(__file__).resolve().parents[2] / "contracts" / "jarvis.demo.v1.schema.json"
    assert contract.SCHEMA.exists()
