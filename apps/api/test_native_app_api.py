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
