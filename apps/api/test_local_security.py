import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import local_security
from local_security import (
    Grant,
    MAX_LOGIN_FAILURES,
    _grants,
    _sessions,
    put_grant_for_tests,
    reset_state,
)
from loopback import ALLOWED_ORIGINS, assert_bind_host
from main import app

PASSPHRASE = "frase-local-de-ensaio"
DEMO_IDS = {
    event["id"]
    for event in json.loads((Path(__file__).resolve().parents[2] / "fixtures/demo.json").read_text())["events"]
}
ALLOWED_ORIGIN = "http://127.0.0.1:3000"
RESOURCE = "calendar:synthetic-primary"


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51000))


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    yield
    reset_state()


def login(client: TestClient, origin: str | None = ALLOWED_ORIGIN, passphrase: str = PASSPHRASE):
    headers = {"origin": origin} if origin is not None else {}
    return client.post("/real/session", json={"passphrase": passphrase}, headers=headers)


def grant(client: TestClient, csrf: str, domains: list[str], *, expires_at: datetime | None = None, resources=None, origin=ALLOWED_ORIGIN):
    body = {
        "connector": "calendar_sim",
        "permission": "read",
        "resource_ids": resources if resources is not None else [RESOURCE],
        "domain_ids": domains,
        "expires_at": (expires_at or (datetime.now(timezone.utc) + timedelta(days=7))).isoformat(),
    }
    headers = {"x-csrf-token": csrf}
    if origin is not None:
        headers["origin"] = origin
    return client.post("/real/grants", json=body, headers=headers)


def csrf_for(client: TestClient) -> str:
    return client.cookies.get("jarvis_session") and next(
        session.csrf_token for session in _sessions.values() if session.token == client.cookies.get("jarvis_session")
    )


def test_demo_stays_separate_and_real_requires_session(client):
    demo = client.get("/events")
    assert demo.status_code == 200
    assert demo.headers["x-jarvis-dataset"] == "demo"
    assert "evt_001" in {item["id"] for item in demo.json()}
    assert client.get("/real/events").status_code == 401
    assert client.get("/real/briefing").status_code == 401


def test_cookie_flags_entropy_expiry_and_no_store(client):
    response = login(client)
    assert response.status_code == 201
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # HTTP loopback local mode
    assert "Max-Age=43200" in cookie
    assert len(client.cookies.get("jarvis_session")) >= 40
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_secure_cookie_is_set_on_https():
    secure_client = TestClient(app, base_url="https://127.0.0.1", client=("127.0.0.1", 51000))
    response = login(secure_client)
    assert response.status_code == 201
    assert "Secure" in response.headers["set-cookie"]


def test_absent_tampered_expired_logout_and_restarted_sessions_fail_closed(client, monkeypatch):
    assert client.get("/real/briefing").status_code == 401
    client.cookies.set("jarvis_session", "token-forjado")
    assert client.get("/real/briefing").status_code == 401
    client.cookies.clear()
    assert login(client).status_code == 201
    old_token = client.cookies.get("jarvis_session")
    session = _sessions[old_token]
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get("/real/briefing").status_code == 401
    assert old_token not in _sessions

    login(client)
    token = client.cookies.get("jarvis_session")
    csrf = csrf_for(client)
    assert client.request("DELETE", "/real/session", headers={"origin": ALLOWED_ORIGIN, "x-csrf-token": csrf}).status_code == 204
    assert client.get("/real/briefing", cookies={"jarvis_session": token}).status_code == 401

    login(client)
    previous_token = client.cookies.get("jarvis_session")
    child_env = {**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE, "OLD_SESSION_TOKEN": previous_token}
    child_code = (
        "from fastapi.testclient import TestClient; from main import app; import os; "
        "c=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',51001)); "
        "c.cookies.set('jarvis_session',os.environ['OLD_SESSION_TOKEN']); print(c.get('/real/briefing').status_code)"
    )
    result = subprocess.run([sys.executable, "-c", child_code], cwd=Path(__file__).parent, env=child_env, capture_output=True, text=True, check=True)
    assert result.stdout.strip().endswith("401")


def test_login_rejects_external_and_missing_origin(client):
    assert login(client, origin="https://evil.example").status_code == 403
    assert login(client, origin=None).status_code == 403


def test_mutations_require_allowed_origin_and_session_bound_csrf(client):
    assert login(client).status_code == 201
    csrf = csrf_for(client)
    body = {
        "connector": "calendar_sim",
        "permission": "read",
        "resource_ids": [RESOURCE],
        "domain_ids": ["dom_synthetic_a"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    }
    assert client.post("/real/grants", json=body, headers={"x-csrf-token": csrf}).status_code == 403
    assert client.post("/real/grants", json=body, headers={"origin": "https://evil.example", "x-csrf-token": csrf}).status_code == 403
    assert client.post("/real/grants", json=body, headers={"origin": ALLOWED_ORIGIN, "x-csrf-token": "csrf-de-outra-sessao"}).status_code == 403
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201


def test_host_external_dns_rebinding_and_public_server_scope_are_rejected(client):
    assert client.get("/events", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/real/events", headers={"host": "evil.example", "origin": "http://127.0.0.1:3000"}).status_code == 400
    assert client.get("/real/events", headers={"origin": "https://evil.example"}).status_code == 403
    # Host permitido não basta se a app recebeu tráfego por interface pública.
    public_client = TestClient(app, base_url="http://203.0.113.10", client=("203.0.113.10", 51000))
    assert public_client.get("/events", headers={"host": "127.0.0.1"}).status_code == 403
    assert public_client.get("/docs", headers={"host": "127.0.0.1"}).status_code == 403
    assert public_client.get("/openapi.json", headers={"host": "127.0.0.1"}).status_code == 403


def test_demo_docs_and_openapi_are_not_served_on_non_loopback_scope(client):
    public_client = TestClient(app, base_url="http://198.51.100.7", client=("198.51.100.7", 51000))
    for route in ("/health", "/briefing", "/events", "/sources", "/inbox", "/domains", "/proposals", "/approvals", "/docs", "/openapi.json", "/real/session"):
        response = public_client.get(route, headers={"host": "localhost"})
        assert response.status_code == 403, (route, response.status_code)


def test_allowed_hosts_and_ipv6_origin_are_explicit():
    assert "https://evil.example" not in ALLOWED_ORIGINS
    assert "http://[::1]:3000" in ALLOWED_ORIGINS
    assert assert_bind_host("127.0.0.1") == "127.0.0.1"
    assert assert_bind_host("::1") == "::1"
    for host in ("0.0.0.0", "::", "192.168.1.2"):
        with pytest.raises(RuntimeError):
            assert_bind_host(host)


def test_grants_are_canonical_expiring_and_resource_scoped(client):
    assert login(client).status_code == 201
    csrf = csrf_for(client)
    headers = {"origin": ALLOWED_ORIGIN, "x-csrf-token": csrf}
    base = {
        "connector": "calendar_sim",
        "permission": "read",
        "resource_ids": [RESOURCE],
        "domain_ids": ["dom_synthetic_a"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    }
    for patch in (
        {"connector": "gmail_sim"},
        {"connector": "other"},
        {"domain_ids": ["dom_unknown"]},
        {"domain_ids": ["dom_medsyn"]},
        {"resource_ids": ["calendar:all"]},
        {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
        {"expires_at": (datetime.now(timezone.utc) + timedelta(days=31)).isoformat()},
        {"expires_at": "2030-01-01T00:00:00"},
    ):
        body = {**base, **patch}
        assert client.post("/real/grants", json=body, headers=headers).status_code == 422, patch
    valid = client.post("/real/grants", json=base, headers=headers)
    assert valid.status_code == 201
    assert valid.json()["connector"] == "calendar_sim"
    assert valid.json()["resource_ids"] == [RESOURCE]
    assert valid.json()["expires_at"]


def test_grant_expiration_denies_aggregate_and_direct_reads(client, monkeypatch):
    login(client)
    csrf = csrf_for(client)
    valid = grant(client, csrf, ["dom_synthetic_a"])
    grant_id = valid.json()["id"]
    base_now = datetime.now(timezone.utc)
    for session in _sessions.values():
        session.expires_at = base_now + timedelta(days=10)
    monkeypatch.setattr(local_security, "_now", lambda: base_now + timedelta(days=8))
    assert client.get("/real/events").status_code == 403
    assert client.get("/real/briefing").status_code == 403
    assert client.get("/real/events/synth_a_1").status_code == 403
    assert _grants[grant_id].expires_at < local_security._now()


def test_duplicate_and_overlapping_grants_are_rejected_and_revoke_is_effective(client):
    login(client)
    csrf = csrf_for(client)
    first = grant(client, csrf, ["dom_synthetic_a"])
    assert first.status_code == 201
    assert client.post("/real/grants", json={
        "connector": "calendar_sim", "permission": "read", "resource_ids": [RESOURCE],
        "domain_ids": ["dom_synthetic_a", "dom_synthetic_b"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=4)).isoformat(),
    }, headers={"origin": ALLOWED_ORIGIN, "x-csrf-token": csrf}).status_code == 409
    revoke = client.post(f"/real/grants/{first.json()['id']}/revoke", headers={"origin": ALLOWED_ORIGIN, "x-csrf-token": csrf})
    assert revoke.status_code == 200
    assert client.get("/real/events").status_code == 403
    assert client.get("/real/events/synth_a_1").status_code == 403
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201


def test_aggregate_and_direct_retrieval_respect_connector_resource_and_domain(client):
    login(client)
    csrf = csrf_for(client)
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201
    aggregate = client.get("/real/events")
    assert aggregate.status_code == 200
    assert [record["id"] for record in aggregate.json()] == ["synth_a_1"]
    assert client.get("/real/events", params={"domain_id": "dom_synthetic_b"}).status_code == 403
    assert client.get("/real/events", params={"domain_id": "dom_unknown"}).status_code == 403
    assert client.get("/real/events/synth_a_1").status_code == 200
    assert client.get("/real/events/synth_b_1").status_code == 404
    assert client.get("/real/events/synth_unclassified_1").status_code == 404
    assert [item["id"] for item in client.get("/real/briefing").json()["items"]] == ["synth_a_1"]


def test_records_with_unknown_connector_resource_or_domain_fail_closed(client):
    login(client)
    csrf = csrf_for(client)
    grant(client, csrf, ["dom_synthetic_a"])
    valid = local_security.SYNTHETIC_RECORDS[0]
    invalid_records = [
        valid.__class__(valid.id, "gmail_sim", RESOURCE, valid.domain_id, valid.title),
        valid.__class__(valid.id, "calendar_sim", "calendar:unknown", valid.domain_id, valid.title),
        valid.__class__(valid.id, "calendar_sim", RESOURCE, "dom_unknown", valid.title),
        valid.__class__(valid.id, "calendar_sim", RESOURCE, None, valid.title),
    ]
    for record in invalid_records:
        monkeypatch_record = local_security.SYNTHETIC_RECORDS
        local_security.SYNTHETIC_RECORDS = (record,)
        assert client.get("/real/events").status_code == 403
        local_security.SYNTHETIC_RECORDS = monkeypatch_record


def test_grant_from_other_principal_does_not_authorize(client):
    login(client)
    put_grant_for_tests(Grant(
        id="other", principal="other", connector="calendar_sim", resource_ids=frozenset({RESOURCE}),
        domain_ids=frozenset({"dom_synthetic_a"}), expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    assert client.get("/real/events").status_code == 403


def test_gmail_grant_cannot_authorize_calendar_even_for_same_domain(client):
    login(client)
    put_grant_for_tests(Grant(
        id="synthetic-wrong-connector", principal="owner", connector="gmail_sim",
        resource_ids=frozenset({RESOURCE}), domain_ids=frozenset({"dom_synthetic_a"}),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    assert client.get("/real/events").status_code == 403
    assert client.get("/real/briefing").status_code == 403


@pytest.mark.parametrize("payload", [
    {"passphrase": "segredo"},
    {"passphrase": "x" * 201},
    {"passphrase": 12345},
])
def test_invalid_credentials_are_never_reflected_or_logged(client, caplog, payload):
    serialized = json.dumps(payload)
    response = client.post("/real/session", content=serialized, headers={"content-type": "application/json", "origin": ALLOWED_ORIGIN})
    assert response.status_code == 422
    for value in ("segredo", "x" * 201, "12345"):
        assert value not in response.text
        assert value not in caplog.text


def test_invalid_json_credential_does_not_echo_body(client):
    body = '{"passphrase":"segredo-malformado"'
    response = client.post("/real/session", content=body, headers={"content-type": "application/json", "origin": ALLOWED_ORIGIN})
    assert response.status_code == 422
    assert "segredo-malformado" not in response.text


def test_login_rate_limit_recovers_after_window(client, monkeypatch):
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    monkeypatch.setattr(local_security, "_now", lambda: now)
    for _ in range(MAX_LOGIN_FAILURES):
        response = login(client, passphrase="senha-errada-comprida")
        assert response.status_code == 401
    locked = login(client)
    assert locked.status_code == 429
    assert locked.headers["retry-after"] == "60"
    monkeypatch.setattr(local_security, "_now", lambda: now + timedelta(seconds=61))
    assert login(client).status_code == 201


def test_rate_limit_recovers_after_process_restart():
    env = {**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE}
    limited = (
        "from fastapi.testclient import TestClient; from main import app; "
        "c=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',51002)); "
        "h={'origin':'http://127.0.0.1:3000'}; "
        "[c.post('/real/session',json={'passphrase':'senha-errada-comprida'},headers=h) for _ in range(8)]; "
        "print(c.post('/real/session',json={'passphrase':'frase-local-de-ensaio'},headers=h).status_code)"
    )
    result = subprocess.run([sys.executable, "-c", limited], cwd=Path(__file__).parent, env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip().endswith("429")
    fresh_process = (
        "from fastapi.testclient import TestClient; from main import app; "
        "c=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',51003)); "
        "print(c.post('/real/session',json={'passphrase':'frase-local-de-ensaio'},headers={'origin':'http://127.0.0.1:3000'}).status_code)"
    )
    restarted = subprocess.run([sys.executable, "-c", fresh_process], cwd=Path(__file__).parent, env=env, capture_output=True, text=True, check=True)
    assert restarted.stdout.strip().endswith("201")


def test_supported_server_entrypoint_disables_proxy_headers(monkeypatch):
    import serve

    captured = {}
    monkeypatch.delenv("JARVIS_BIND_HOST", raising=False)
    monkeypatch.setattr(serve.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    serve.main()
    assert captured["host"] == "127.0.0.1"
    assert captured["proxy_headers"] is False
    assert captured["forwarded_allow_ips"] == ""


def test_supported_entrypoint_rejects_public_bind_before_uvicorn(monkeypatch):
    import serve

    monkeypatch.setenv("JARVIS_BIND_HOST", "0.0.0.0")
    monkeypatch.setattr(serve.uvicorn, "run", lambda *args, **kwargs: pytest.fail("uvicorn não deveria iniciar"))
    with pytest.raises(RuntimeError):
        serve.main()


def test_direct_uvicorn_cli_refuses_to_start_without_guarded_runner():
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "18761"],
        cwd=Path(__file__).parent,
        env={**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "use python serve.py" in result.stderr
