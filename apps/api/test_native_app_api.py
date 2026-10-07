from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import quote, unquote

import pytest
from fastapi.testclient import TestClient

from local_security import reset_state
from main import create_native_app
from mission_repository import MissionRepository
from native_runtime import NativeRuntimeIdentity

PASSPHRASE = "senha-sintetica-mac003"
HEADERS = {"content-type": "text/plain", "connection": "close"}


def body(**fields: str) -> str:
    return "".join(f"{key}={quote(value, safe='-_.~')}\n" for key, value in fields.items())


def fields(response) -> dict[str, str]:
    return {
        name: unquote(value, encoding="utf-8", errors="strict")
        for name, value in (line.split("=", 1) for line in response.text.splitlines())
    }


@pytest.fixture
def native_client(tmp_path, monkeypatch):
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    identity = NativeRuntimeIdentity(
        instance_id="test-generation-1",
        secret=bytearray(b"s" * 32),
        directory_dev=1,
        directory_ino=1,
    )
    identity.acknowledged.set()
    app = create_native_app(identity, database_path=tmp_path / "private" / "memory.sqlite3")
    with TestClient(app, base_url="http://jarvis.local", client=("127.0.0.1", 54001)) as client:
        client.headers.clear()
        yield client
    reset_state()
    identity.clear()


def login(client: TestClient) -> tuple[str, str]:
    opened = client.post(
        "/v1/app/session/open",
        content=body(passphrase=PASSPHRASE),
        headers=HEADERS,
    )
    result = fields(opened)
    assert result["ok"] == "true"
    assert int(result["expires_at_epoch"]) > int(time.time())
    return result["session_token"], result["csrf_token"]


def test_native_g5_requires_explicit_session_and_grant(native_client):
    denied_without_session = native_client.post(
        "/v1/app/missions/list",
        content=body(session_token="", domain_id="dom_synthetic_a"),
        headers=HEADERS,
    )
    assert fields(denied_without_session) == {"ok": "false", "code": "session_required"}

    wrong = native_client.post(
        "/v1/app/session/open",
        content=body(passphrase="senha-errada-para-teste"),
        headers=HEADERS,
    )
    assert fields(wrong) == {"ok": "false", "code": "credential_rejected"}
    assert PASSPHRASE not in wrong.text

    session_token, csrf_token = login(native_client)
    denied_without_grant = native_client.post(
        "/v1/app/missions/list",
        content=body(session_token=session_token, domain_id="dom_synthetic_a"),
        headers=HEADERS,
    )
    assert fields(denied_without_grant) == {"ok": "false", "code": "grant_required"}

    client_store = native_client.app.state.memory_store
    MissionRepository(client_store).create(
        "owner", "Missão sintética MAC-003", "dom_synthetic_a", "mac003-native-seed"
    )
    grant = native_client.post(
        "/v1/app/grants/mission-read",
        content=body(
            session_token=session_token,
            csrf_token=csrf_token,
            domain_id="dom_synthetic_a",
        ),
        headers=HEADERS,
    )
    grant_fields = fields(grant)
    assert grant_fields["ok"] == "true"
    assert grant_fields["domain_id"] == "dom_synthetic_a"
    assert int(grant_fields["expires_at_epoch"]) > int(time.time())
    assert datetime.fromisoformat(grant_fields["expires_at"]).tzinfo is not None

    read = native_client.post(
        "/v1/app/missions/list",
        content=body(session_token=session_token, domain_id="dom_synthetic_a"),
        headers=HEADERS,
    )
    read_fields = fields(read)
    assert read_fields == {
        "ok": "true",
        "dataset": "api_synthetic",
        "count": "1",
        "mission_id": read_fields["mission_id"],
        "title": "Missão sintética MAC-003",
        "domain_id": "dom_synthetic_a",
        "status": "planned",
        "revision": "1",
    }

    revoked = native_client.post(
        "/v1/app/grants/mission-read/revoke",
        content=body(
            session_token=session_token,
            csrf_token=csrf_token,
            grant_id=grant_fields["grant_id"],
        ),
        headers=HEADERS,
    )
    assert fields(revoked) == {"ok": "true", "revoked": "true"}
    denied_after_revoke = native_client.post(
        "/v1/app/missions/list",
        content=body(session_token=session_token, domain_id="dom_synthetic_a"),
        headers=HEADERS,
    )
    assert fields(denied_after_revoke) == {"ok": "false", "code": "grant_required"}
    closed = native_client.post(
        "/v1/app/session/close",
        content=body(session_token=session_token, csrf_token=csrf_token),
        headers=HEADERS,
    )
    assert fields(closed) == {"ok": "true", "closed": "true"}


def test_native_surface_is_closed_and_does_not_mount_web_routes(native_client):
    assert native_client.request("GET", "/docs", content=b"", headers=HEADERS).status_code == 404
    assert native_client.request("GET", "/real/missions", content=b"", headers=HEADERS).status_code == 404
    assert native_client.post(
        "/v1/app/missions/list?cursor=old",
        content=body(session_token="x" * 43, domain_id="dom_synthetic_a"),
        headers=HEADERS,
    ).status_code == 400
    assert native_client.post(
        "/v1/app/missions/list",
        content=body(session_token="x" * 43, domain_id="dom_synthetic_a"),
        headers={**HEADERS, "origin": "tauri://localhost"},
    ).status_code == 400
    assert native_client.post(
        "/v1/app/missions/list",
        content=body(session_token="x" * 43, domain_id="dom_synthetic_a"),
        headers={**HEADERS, "x-forwarded-host": "jarvis.local"},
    ).status_code == 400
    oversized = "x" * 1025
    assert native_client.post(
        "/v1/app/session/open",
        content=oversized,
        headers=HEADERS,
    ).status_code == 413


def test_native_grant_requires_csrf_and_rejects_other_domains(native_client):
    session_token, csrf_token = login(native_client)
    missing_csrf = native_client.post(
        "/v1/app/grants/mission-read",
        content=body(session_token=session_token, csrf_token="wrong", domain_id="dom_synthetic_a"),
        headers=HEADERS,
    )
    assert fields(missing_csrf) == {"ok": "false", "code": "session_required"}

    wrong_domain = native_client.post(
        "/v1/app/grants/mission-read",
        content=body(session_token=session_token, csrf_token=csrf_token, domain_id="dom_synthetic_b"),
        headers=HEADERS,
    )
    assert fields(wrong_domain) == {"ok": "false", "code": "scope_invalid"}


@pytest.mark.parametrize("end_session", ["close", "expire"])
def test_grants_are_session_bound_and_invalidated_atomically(native_client, monkeypatch, end_session):
    from datetime import timedelta
    import local_security as security

    instant = security._now()
    monkeypatch.setattr(security, "_now", lambda: instant)
    monkeypatch.setattr("native_app_api._now", lambda: instant)

    def call(path, **values):
        return fields(native_client.post("/v1/app/" + path, content=body(**values), headers=HEADERS))

    s1, csrf1 = login(native_client)
    g1 = call("grants/mission-read", session_token=s1, csrf_token=csrf1, domain_id="dom_synthetic_a")
    assert g1["ok"] == "true"
    assert security._grants[g1["grant_id"]].session_token == s1
    s2, csrf2 = login(native_client)
    assert call("missions/list", session_token=s2, domain_id="dom_synthetic_a") == {"ok": "false", "code": "grant_required"}
    assert call("grants/mission-read/revoke", session_token=s2, csrf_token=csrf2, grant_id=g1["grant_id"]) == {"ok": "false", "code": "grant_required"}
    g2 = call("grants/mission-read", session_token=s2, csrf_token=csrf2, domain_id="dom_synthetic_a")
    assert g2["ok"] == "true"
    assert call("grants/mission-read", session_token=s2, csrf_token=csrf2, domain_id="dom_synthetic_a")["code"] == "grant_conflict"
    for _ in range(2):
        assert call("grants/mission-read/revoke", session_token=s2, csrf_token=csrf2, grant_id=g2["grant_id"]) == {"ok": "true", "revoked": "true"}
    assert call("missions/list", session_token=s2, domain_id="dom_synthetic_a")["code"] == "grant_required"
    if end_session == "close":
        assert call("session/close", session_token=s1, csrf_token=csrf1) == {"ok": "true", "closed": "true"}
    else:
        security._sessions[s1].expires_at = instant + timedelta(seconds=1)
        instant += timedelta(seconds=1)
        assert call("missions/list", session_token=s1, domain_id="dom_synthetic_a")["code"] == "session_required"
    assert s1 not in security._sessions
    assert security._grants[g1["grant_id"]].revoked
    s3, csrf3 = login(native_client)
    assert call("missions/list", session_token=s3, domain_id="dom_synthetic_a")["code"] == "grant_required"
    assert call("grants/mission-read", session_token=s3, csrf_token=csrf3, domain_id="dom_synthetic_a")["ok"] == "true"


def test_expiry_swept_before_new_consent(native_client):
    from datetime import timedelta
    import local_security as security
    s1, csrf1 = login(native_client)
    response = fields(native_client.post("/v1/app/grants/mission-read", content=body(
        session_token=s1, csrf_token=csrf1, domain_id="dom_synthetic_a"), headers=HEADERS))
    security._sessions[s1].expires_at = security._now() - timedelta(seconds=1)
    s2, csrf2 = login(native_client)
    new = fields(native_client.post("/v1/app/grants/mission-read", content=body(
        session_token=s2, csrf_token=csrf2, domain_id="dom_synthetic_a"), headers=HEADERS))
    assert new["ok"] == "true"
    assert s1 not in security._sessions
    assert security._grants[response["grant_id"]].revoked


def test_close_and_read_snapshot_share_the_authorization_lock(native_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import local_security as security

    token, csrf = login(native_client)
    grant = fields(native_client.post("/v1/app/grants/mission-read", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a"), headers=HEADERS))
    session = security._native_session(token, csrf, mutation=True)
    started = Event()

    def close():
        started.set()
        security._close_session_for(session)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with security.mission_read_scope_confirmed("owner", "dom_synthetic_a", token):
            pending = executor.submit(close)
            assert started.wait(2)
            assert not pending.done()
            assert token in security._sessions
            assert not security._grants[grant["grant_id"]].revoked
        pending.result(timeout=2)
    assert token not in security._sessions
    assert security._grants[grant["grant_id"]].revoked
    with pytest.raises(PermissionError):
        with security.mission_read_scope_confirmed("owner", "dom_synthetic_a", token):
            pytest.fail("closed session authorized a new snapshot")


def test_expired_session_invalidates_grants_during_mutation_revalidation(native_client, monkeypatch):
    from datetime import timedelta
    from fastapi import HTTPException
    import local_security as security

    token, csrf = login(native_client)
    response = fields(native_client.post("/v1/app/grants/mission-read", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a"), headers=HEADERS))
    stale_session = security._native_session(token, csrf, mutation=True)
    grant_body = security.GrantIn(connector="mission_sim", permission="read",
        resource_ids=["mission:read"], domain_ids=["dom_synthetic_a"],
        expires_at=security._now() + timedelta(minutes=10))
    boundary = stale_session.expires_at
    monkeypatch.setattr(security, "_now", lambda: boundary)
    with pytest.raises(HTTPException) as denied:
        security._create_grant_for_session(stale_session, grant_body)
    assert denied.value.status_code == 401
    assert token not in security._sessions
    assert security._grants[response["grant_id"]].revoked
