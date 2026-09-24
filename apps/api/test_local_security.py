import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_security import Grant, put_grant_for_tests, reset_state
from loopback import ALLOWED_ORIGINS, assert_bind_host
from main import app

PASSPHRASE = "frase-local-de-ensaio"
DEMO_IDS = {
    event["id"]
    for event in json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "demo.json").read_text())["events"]
}

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    yield
    reset_state()


def login(origin: str | None = "http://127.0.0.1:3000"):
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    response = client.post("/real/session", json={"passphrase": PASSPHRASE}, headers=headers)
    assert response.status_code == 201, response.text
    return response


def grant(csrf: str, domains: list[str], origin: str = "http://127.0.0.1:3000"):
    response = client.post(
        "/real/grants",
        json={"connector": "calendar_sim", "permission": "read", "domain_ids": domains},
        headers={"x-csrf-token": csrf, "origin": origin},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_demo_routes_stay_open_and_separate():
    demo = client.get("/events")
    assert demo.status_code == 200
    assert demo.headers["x-jarvis-dataset"] == "demo"
    assert "evt_001" in {event["id"] for event in demo.json()}
    real = client.get("/real/events")
    assert real.status_code == 401
    assert real.headers["x-jarvis-dataset"] == "real"


def test_session_cookie_is_http_only_and_not_echoed():
    response = login()
    cookie = response.headers["set-cookie"]
    assert "jarvis_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie
    body = response.json()
    assert "jarvis_session" not in cookie.split(";", 1)[0] or body["csrf_token"] not in cookie
    assert body["csrf_token"] not in cookie
    assert body["dataset"] == "real"
    assert PASSPHRASE not in response.text


def test_missing_or_wrong_session_is_denied():
    assert client.get("/real/briefing").status_code == 401
    fresh = TestClient(app)
    fresh.cookies.set("jarvis_session", "token-adivinhado")
    denied = fresh.get("/real/briefing")
    assert denied.status_code == 401


def test_csrf_and_origin_are_required_for_changes():
    csrf = login().json()["csrf_token"]
    missing = client.post(
        "/real/grants",
        json={"connector": "calendar_sim", "permission": "read", "domain_ids": ["dom_saude"]},
    )
    assert missing.status_code == 403
    evil = client.post(
        "/real/grants",
        json={"connector": "calendar_sim", "permission": "read", "domain_ids": ["dom_saude"]},
        headers={"x-csrf-token": csrf, "origin": "https://evil.example"},
    )
    assert evil.status_code == 403
    created = grant(csrf, ["dom_saude"])
    assert created["permission"] == "read"
    assert created["domain_ids"] == ["dom_saude"]


def test_grant_is_required_and_revocation_blocks_later_reads():
    csrf = login().json()["csrf_token"]
    assert client.get("/real/events").status_code == 403
    created = grant(csrf, ["dom_saude"])
    visible = client.get("/real/events")
    assert visible.status_code == 200
    assert [item["id"] for item in visible.json()] == ["synth_saude_1"]
    revoked = client.post(
        f"/real/grants/{created['id']}/revoke",
        headers={"x-csrf-token": csrf, "origin": "http://127.0.0.1:3000"},
    )
    assert revoked.status_code == 200
    assert client.get("/real/events").status_code == 403
    assert client.get("/real/briefing").status_code == 403


def test_aggregate_read_cannot_cross_domain_grants():
    csrf = login().json()["csrf_token"]
    grant(csrf, ["dom_saude"])
    medsyn = client.get("/real/events", params={"domain_id": "dom_medsyn"})
    assert medsyn.status_code == 403
    aggregated = client.get("/real/events").json()
    assert {item["domain_id"] for item in aggregated} == {"dom_saude"}
    assert all("CRIVO" not in item["title"] for item in aggregated)
    briefing = client.get("/real/briefing").json()
    assert {item["id"] for item in briefing["items"]} == {"synth_saude_1"}
    assert DEMO_IDS.isdisjoint({item["id"] for item in briefing["items"]})


def test_explicit_grant_keeps_classification_distinct_from_permission():
    csrf = login().json()["csrf_token"]
    grant(csrf, ["dom_medsyn", "dom_crivo"])
    rows = client.get("/real/events").json()
    by_id = {row["id"]: row for row in rows}
    assert by_id["synth_medsyn_1"]["domain_id"] == "dom_medsyn"
    assert "CRIVO" in by_id["synth_medsyn_1"]["title"]
    assert by_id["synth_crivo_1"]["domain_id"] == "dom_crivo"
    assert "MedSyn" in by_id["synth_crivo_1"]["title"]
    assert "synth_saude_1" not in by_id


def test_grant_for_another_principal_does_not_authorize_owner():
    login()
    put_grant_for_tests(
        Grant(
            id="grant_other",
            principal="other",
            connector="calendar_sim",
            permission="read",
            domain_ids=frozenset({"dom_saude"}),
        )
    )
    assert client.get("/real/events").status_code == 403


def test_wrong_passphrase_is_rejected_without_echo():
    response = client.post("/real/session", json={"passphrase": "senha-errada-longa"})
    assert response.status_code == 401
    assert "senha-errada-longa" not in response.text


def test_bind_host_rejects_public_interfaces():
    assert assert_bind_host("127.0.0.1") == "127.0.0.1"
    with pytest.raises(RuntimeError):
        assert_bind_host("0.0.0.0")
    assert "https://evil.example" not in ALLOWED_ORIGINS


def test_secure_cookie_when_request_is_https():
    https_client = TestClient(app, base_url="https://127.0.0.1")
    response = https_client.post("/real/session", json={"passphrase": PASSPHRASE})
    assert response.status_code == 201
    assert "Secure" in response.headers["set-cookie"]
