import json
import ipaddress
import os
import sqlite3
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

import local_security
from memory_models import EventRecord, ProvenanceRecord, SourceRecord
from local_security import (
    Grant,
    MAX_LOGIN_FAILURES,
    _grants,
    _sessions,
    put_grant_for_tests,
    reset_state,
)
from loopback import ALLOWED_ORIGINS, assert_bind_host
from main import create_app
from server_config import LocalServerConfig

PASSPHRASE = "frase-local-de-ensaio"
DEMO_IDS = {
    event["id"]
    for event in json.loads((Path(__file__).resolve().parents[2] / "fixtures/demo.json").read_text())["events"]
}
ALLOWED_ORIGIN = "http://127.0.0.1:3000"
RESOURCE = "calendar:synthetic-primary"


@pytest.fixture
def client():
    app = create_app(LocalServerConfig())
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51000)) as test_client:
        _seed_test_catalog(app.state.memory_store)
        yield test_client


@pytest.fixture
def empty_client():
    app = create_app(LocalServerConfig())
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51000)) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    monkeypatch.setenv("JARVIS_DATABASE_PATH", str(tmp_path / "jarvis-private" / "memory.sqlite3"))
    yield
    reset_state()


def _seed_test_catalog(store):
    source_id = "src_calendar_test"
    store.save_source(SourceRecord(
        id=source_id,
        provider="calendar_sim",
        resource_id=RESOURCE,
        sync_status="disconnected",
    ))
    observed = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    eight_domain_records = []
    letters = "abcdefgh"
    for index, letter in enumerate(letters):
        domain_id = f"dom_synthetic_{letter}"
        mentioned_domain = f"dom_synthetic_{letters[-index - 1]}"
        event_id = f"real_evt_synth_{letter}_1"
        title = f"evento sintético classificado em {domain_id}; título menciona {mentioned_domain}"
        eight_domain_records.append((event_id, domain_id, title))
    eight_domain_records.append(("real_evt_synth_unclassified_1", None, "registro sintético não classificado"))
    for event_id, domain_id, title in eight_domain_records:
        classified = domain_id is not None
        store.save_event(EventRecord(
            id=event_id,
            event_type="appointment",
            title=title,
            domain_id=domain_id,
            occurred_at=observed,
            provenance=ProvenanceRecord(
                source_id=source_id,
                external_ref=f"external-{event_id}",
                observed_at=observed,
                last_verified_at=observed,
                confidence=0.9,
                classification_method="human_review" if classified else "unclassified",
                classified_at=observed if classified else None,
            ),
        ))


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


def test_session_without_grant_cannot_list_read_by_id_or_build_briefing(client, monkeypatch):
    assert login(client).status_code == 201
    def query_without_grant(*_args, **_kwargs):
        pytest.fail("consulta ao banco não deve ocorrer sem concessão ativa")

    monkeypatch.setattr(client.app.state.memory_store, "list_authorized_events", query_without_grant)
    monkeypatch.setattr(client.app.state.memory_store, "get_authorized_event", query_without_grant)
    assert client.get("/real/events").status_code == 403
    assert client.get("/real/events/real_evt_synth_a_1").status_code == 403
    assert client.get("/real/briefing").status_code == 403


def test_real_database_starts_empty_and_never_imports_demo_fixture(empty_client):
    assert "evt_001" in {record["id"] for record in empty_client.get("/events").json()}
    assert login(empty_client).status_code == 201
    csrf = csrf_for(empty_client)
    assert grant(empty_client, csrf, ["dom_synthetic_a"]).status_code == 201
    assert empty_client.get("/real/events").status_code == 403
    assert empty_client.get("/real/briefing").status_code == 403
    assert empty_client.get("/real/events/evt_001").status_code == 404
    with sqlite3.connect(empty_client.app.state.memory_store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "grants" not in tables
        assert "sessions" not in tables


def test_storage_query_failure_returns_generic_service_unavailable(client, monkeypatch):
    assert login(client).status_code == 201
    csrf = csrf_for(client)
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201

    def fail_read(*_args, **_kwargs):
        raise sqlite3.OperationalError("private path and record payload must not leak")

    monkeypatch.setattr(client.app.state.memory_store, "list_authorized_events", fail_read)
    response = client.get("/real/events")
    assert response.status_code == 503
    assert response.json() == {"detail": "memória local indisponível"}
    assert "private path" not in response.text


def test_malformed_persisted_record_is_omitted_without_crashing_api(client):
    assert login(client).status_code == 201
    csrf = csrf_for(client)
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201
    with sqlite3.connect(client.app.state.memory_store.path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE events SET payload_json='{' WHERE id='real_evt_synth_a_1'")
        connection.commit()
    assert client.get("/real/events").status_code == 403
    assert client.get("/real/events/real_evt_synth_a_1").status_code == 404
    assert client.get("/real/briefing").status_code == 403


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
    secure_client = TestClient(create_app(LocalServerConfig()), base_url="https://127.0.0.1", client=("127.0.0.1", 51000))
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
        "from fastapi.testclient import TestClient; from main import create_app; from server_config import LocalServerConfig; import os; "
        "c=TestClient(create_app(LocalServerConfig()),base_url='http://127.0.0.1',client=('127.0.0.1',51001)); "
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
    public_client = TestClient(create_app(LocalServerConfig()), base_url="http://203.0.113.10", client=("203.0.113.10", 51000))
    assert public_client.get("/events", headers={"host": "127.0.0.1"}).status_code == 403
    assert public_client.get("/docs", headers={"host": "127.0.0.1"}).status_code == 403
    assert public_client.get("/openapi.json", headers={"host": "127.0.0.1"}).status_code == 403


def test_demo_docs_and_openapi_are_not_served_on_non_loopback_scope(client):
    public_client = TestClient(create_app(LocalServerConfig()), base_url="http://198.51.100.7", client=("198.51.100.7", 51000))
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


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_factory_accepts_exact_valid_loopback_configuration(host):
    app = create_app(LocalServerConfig(host=host, port=8123))
    assert app.title == "JARVIS API — Gate 1 mock"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.25"])
def test_local_config_rejects_non_loopback_bind_addresses(host):
    with pytest.raises(RuntimeError):
        LocalServerConfig(host=host)


def test_factory_rejects_missing_fake_subclass_and_corrupted_config():
    with pytest.raises(TypeError):
        create_app()
    with pytest.raises(TypeError, match="instância exata"):
        create_app(SimpleNamespace(host="127.0.0.1", port=8000, validate=lambda: None))

    class ExtendedConfig(LocalServerConfig):
        pass

    extended = object.__new__(ExtendedConfig)
    object.__setattr__(extended, "host", "127.0.0.1")
    object.__setattr__(extended, "port", 8000)
    with pytest.raises(TypeError, match="instância exata"):
        create_app(extended)

    corrupted = object.__new__(LocalServerConfig)
    object.__setattr__(corrupted, "host", "0.0.0.0")
    object.__setattr__(corrupted, "port", 8000)
    with pytest.raises(RuntimeError):
        create_app(corrupted)

    corrupted_port = object.__new__(LocalServerConfig)
    object.__setattr__(corrupted_port, "host", "127.0.0.1")
    object.__setattr__(corrupted_port, "port", True)
    with pytest.raises(ValueError, match="porta"):
        create_app(corrupted_port)


def test_factory_revalidates_configuration_at_lifespan_startup():
    config = LocalServerConfig()
    app = create_app(config)
    object.__setattr__(config, "host", "0.0.0.0")
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pytest.fail("a aplicação não deveria iniciar com configuração adulterada")


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
    assert client.get("/real/events/real_evt_synth_a_1").status_code == 403
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
    assert client.get("/real/events/real_evt_synth_a_1").status_code == 403
    assert client.get("/real/briefing").status_code == 403
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201


def test_aggregate_and_direct_retrieval_respect_connector_resource_and_domain(client):
    login(client)
    csrf = csrf_for(client)
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201
    aggregate = client.get("/real/events")
    assert aggregate.status_code == 200
    assert [record["id"] for record in aggregate.json()] == ["real_evt_synth_a_1"]
    assert client.get("/real/events", params={"domain_id": "dom_synthetic_b"}).status_code == 403
    assert client.get("/real/events", params={"domain_id": "dom_unknown"}).status_code == 403
    assert client.get("/real/events/real_evt_synth_a_1").status_code == 200
    assert client.get("/real/events/real_evt_synth_b_1").status_code == 404
    assert client.get("/real/events/real_evt_synth_unclassified_1").status_code == 404
    assert [item["id"] for item in client.get("/real/briefing").json()["items"]] == ["real_evt_synth_a_1"]


def test_all_eight_synthetic_domains_are_isolated_by_explicit_domain_id(client):
    assert login(client).status_code == 201
    csrf = csrf_for(client)
    letters = "abcdefgh"
    for index, letter in enumerate(letters):
        domain_id = f"dom_synthetic_{letter}"
        expected_id = f"real_evt_synth_{letter}_1"
        next_letter = letters[(index + 1) % len(letters)]
        next_id = f"real_evt_synth_{next_letter}_1"

        grant_response = grant(client, csrf, [domain_id])
        assert grant_response.status_code == 201
        listing = client.get("/real/events")
        assert listing.status_code == 200
        assert [event["id"] for event in listing.json()] == [expected_id]
        assert domain_id in listing.json()[0]["title"]
        assert client.get("/real/events", params={"domain_id": domain_id}).json()[0]["id"] == expected_id
        assert client.get("/real/events", params={"domain_id": f"dom_synthetic_{next_letter}"}).status_code == 403
        assert client.get(f"/real/events/{next_id}").status_code == 404
        assert [event["id"] for event in client.get("/real/briefing").json()["items"]] == [expected_id]

        revoked = client.post(
            f"/real/grants/{grant_response.json()['id']}/revoke",
            headers={"origin": ALLOWED_ORIGIN, "x-csrf-token": csrf},
        )
        assert revoked.status_code == 200
        assert client.get("/real/events").status_code == 403
        assert client.get(f"/real/events/{expected_id}").status_code == 403
        assert client.get("/real/briefing").status_code == 403


def test_grants_are_volatile_even_when_database_survives_process_restart(client):
    assert login(client).status_code == 201
    csrf = csrf_for(client)
    assert grant(client, csrf, ["dom_synthetic_a"]).status_code == 201
    assert [event["id"] for event in client.get("/real/events").json()] == ["real_evt_synth_a_1"]

    child_env = {**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE}
    child_code = (
        "from fastapi.testclient import TestClient\n"
        "from main import create_app\n"
        "from server_config import LocalServerConfig\n"
        "with TestClient(create_app(LocalServerConfig()),base_url='http://127.0.0.1',client=('127.0.0.1',51004)) as c:\n"
        f" assert c.post('/real/session',json={{'passphrase':'{PASSPHRASE}'}},headers={{'origin':'{ALLOWED_ORIGIN}'}}).status_code==201\n"
        " print(c.get('/real/events').status_code,c.get('/real/events/real_evt_synth_a_1').status_code,c.get('/real/briefing').status_code)"
    )
    restarted = subprocess.run(
        [sys.executable, "-c", child_code], cwd=Path(__file__).parent,
        env=child_env, capture_output=True, text=True, timeout=15,
    )
    assert restarted.returncode == 0, restarted.stderr
    assert restarted.stdout.strip().endswith("403 403 403")


def test_records_with_unknown_connector_resource_or_domain_fail_closed(client):
    login(client)
    csrf = csrf_for(client)
    grant(client, csrf, ["dom_synthetic_a"])
    with pytest.raises(ValidationError):
        SourceRecord(id="src_unknown_connector", provider="gmail_sim", resource_id=RESOURCE)
    with pytest.raises(ValidationError):
        SourceRecord(id="src_unknown_resource", provider="calendar_sim", resource_id="calendar:unknown")
    with pytest.raises(ValidationError):
        EventRecord(
            id="unknown-domain", event_type="appointment", title="malformed synthetic",
            domain_id="dom_unknown", provenance=ProvenanceRecord(
                source_id="src_calendar_test", observed_at=datetime.now(timezone.utc),
                classification_method="human_review", classified_at=datetime.now(timezone.utc),
            ),
        )
    assert client.get("/real/events").status_code == 200
    assert [event["id"] for event in client.get("/real/events").json()] == ["real_evt_synth_a_1"]
    assert client.get("/real/events/real_evt_synth_unclassified_1").status_code == 404


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
        "from fastapi.testclient import TestClient; from main import create_app; from server_config import LocalServerConfig; "
        "c=TestClient(create_app(LocalServerConfig()),base_url='http://127.0.0.1',client=('127.0.0.1',51002)); "
        "h={'origin':'http://127.0.0.1:3000'}; "
        "[c.post('/real/session',json={'passphrase':'senha-errada-comprida'},headers=h) for _ in range(8)]; "
        "print(c.post('/real/session',json={'passphrase':'frase-local-de-ensaio'},headers=h).status_code)"
    )
    result = subprocess.run([sys.executable, "-c", limited], cwd=Path(__file__).parent, env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip().endswith("429")
    fresh_process = (
        "from fastapi.testclient import TestClient; from main import create_app; from server_config import LocalServerConfig; "
        "c=TestClient(create_app(LocalServerConfig()),base_url='http://127.0.0.1',client=('127.0.0.1',51003)); "
        "print(c.post('/real/session',json={'passphrase':'frase-local-de-ensaio'},headers={'origin':'http://127.0.0.1:3000'}).status_code)"
    )
    restarted = subprocess.run([sys.executable, "-c", fresh_process], cwd=Path(__file__).parent, env=env, capture_output=True, text=True, check=True)
    assert restarted.stdout.strip().endswith("201")


def test_supported_server_entrypoint_disables_proxy_headers(monkeypatch):
    import serve

    captured = {}
    monkeypatch.delenv("JARVIS_BIND_HOST", raising=False)
    monkeypatch.setattr(
        serve.uvicorn,
        "run",
        lambda *args, **kwargs: (captured.update(kwargs), captured.update(app=args[0])),
    )
    serve.main()
    assert captured["app"].title == "JARVIS API — Gate 1 mock"
    assert captured["host"] == "127.0.0.1"
    assert captured["proxy_headers"] is False
    assert captured["forwarded_allow_ips"] == ""


def test_supported_entrypoint_rejects_public_bind_before_uvicorn(monkeypatch):
    import serve

    monkeypatch.setenv("JARVIS_BIND_HOST", "0.0.0.0")
    monkeypatch.setattr(serve.uvicorn, "run", lambda *args, **kwargs: pytest.fail("uvicorn não deveria iniciar"))
    with pytest.raises(RuntimeError):
        serve.main()
    with pytest.raises(RuntimeError):
        LocalServerConfig(host="0.0.0.0")


def test_direct_uvicorn_cli_refuses_to_start_without_guarded_runner():
    port = _free_port()
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(port)],
        cwd=Path(__file__).parent,
        env={**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert not _port_accepts("127.0.0.1", port)


def test_programmatic_uvicorn_import_string_refuses_to_start_before_listening():
    port = _free_port()
    command = (
        "import uvicorn; "
        f"uvicorn.run('main:app', host='0.0.0.0', port={port}, log_level='critical')"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=Path(__file__).parent,
        env={**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert not _port_accepts("127.0.0.1", port)


def test_uvicorn_factory_without_local_configuration_fails_before_listening():
    port = _free_port()
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "main:create_app", "--factory", "--host", "0.0.0.0", "--port", str(port)],
        cwd=Path(__file__).parent,
        env={**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "config" in result.stderr
    assert not _port_accepts("127.0.0.1", port)


def test_fake_configuration_cannot_start_a_public_uvicorn_listener():
    port = _free_port()
    command = (
        "from types import SimpleNamespace; import uvicorn; from main import create_app; "
        "fake=SimpleNamespace(host='127.0.0.1', port=8000, validate=lambda: None); "
        f"uvicorn.run(create_app(fake), host='0.0.0.0', port={port}, log_level='critical')"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=Path(__file__).parent,
        env={**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "instância exata de LocalServerConfig" in result.stderr
    assert not _port_accepts("127.0.0.1", port)


def test_real_socket_supported_runner_is_loopback_only_and_serves_expected_routes():
    port = _free_port()
    env = {
        **os.environ,
        "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE,
        "JARVIS_BIND_HOST": "127.0.0.1",
        "JARVIS_BIND_PORT": str(port),
    }
    process = subprocess.Popen(
        [sys.executable, "serve.py"],
        cwd=Path(__file__).parent,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        client = _wait_for_http_server(process, port)
        for route in ("/health", "/events", "/docs", "/openapi.json"):
            assert client.get(route).status_code == 200, route
        assert client.get("/real/events").status_code == 401
        lan_address = _lan_ipv4()
        if lan_address:
            with pytest.raises(httpx.ConnectError):
                httpx.get(f"http://{lan_address}:{port}/health", timeout=0.5)
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_real_socket_non_loopback_scope_denies_demo_docs_openapi_and_real_routes():
    port = _free_port()
    env = {**os.environ, "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE}
    command = (
        "import uvicorn; from main import create_app; from server_config import LocalServerConfig; "
        f"uvicorn.run(create_app(LocalServerConfig()), host='0.0.0.0', port={port}, "
        "proxy_headers=False, access_log=False, log_level='critical')"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", command],
        cwd=Path(__file__).parent,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        client = _wait_for_http_server(process, port)
        assert client.get("/health").status_code == 200
        assert client.get("/events").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/real/events").status_code == 401
        lan_address = _lan_ipv4()
        if not lan_address:
            pytest.skip("nenhum endereço IPv4 LAN detectado para probe de socket")
        for route in ("/health", "/events", "/docs", "/openapi.json", "/real/events"):
            response = httpx.get(
                f"http://{lan_address}:{port}{route}",
                headers={"host": f"localhost:{port}", "x-forwarded-for": "127.0.0.1"},
                timeout=2,
            )
            assert response.status_code == 403, (route, response.status_code)
    finally:
        process.terminate()
        process.wait(timeout=5)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _port_accepts(host: str, port: int) -> bool:
    with socket.socket() as client:
        client.settimeout(0.2)
        return client.connect_ex((host, port)) == 0


def _wait_for_http_server(process: subprocess.Popen, port: int) -> httpx.Client:
    deadline = time.monotonic() + 8
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"servidor encerrou durante startup: {process.returncode}")
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return client
        except httpx.HTTPError:
            time.sleep(0.05)
    client.close()
    raise AssertionError("servidor não iniciou em loopback")


def _lan_ipv4() -> str | None:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, check=True)
            address = result.stdout.strip()
            if address and not ipaddress.ip_address(address).is_loopback:
                return address
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            address = result[4][0]
            if not ipaddress.ip_address(address).is_loopback:
                return address
    except OSError:
        pass
    return None
