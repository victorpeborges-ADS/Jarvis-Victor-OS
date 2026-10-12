from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import quote, unquote

import httpx
import pytest
from fastapi.testclient import TestClient

from local_security import reset_state
from main import create_native_app
from mission_repository import MissionRepository
from native_runtime import (
    ENVELOPE_ROUTE,
    ENVELOPE_VERSION,
    NativeRuntimeIdentity,
    _open_application_envelope,
    _seal_application_envelope,
)

PASSPHRASE = "senha-sintetica-mac003"
HEADERS = {"content-type": "text/plain", "connection": "close"}
ENVELOPE_HEADERS = {"content-type": "application/octet-stream", "connection": "close"}


def body(**fields: str) -> str:
    return "".join(f"{key}={quote(value, safe='-_.~')}\n" for key, value in fields.items())


def fields(response) -> dict[str, str]:
    return {
        name: unquote(value, encoding="utf-8", errors="strict")
        for name, value in (line.split("=", 1) for line in response.text.splitlines())
    }


class AuthenticatedNativeTestClient:
    def __init__(self, raw: TestClient, identity: NativeRuntimeIdentity):
        self.raw = raw
        self.identity = identity
        self.app = raw.app
        self.sequence = 0

    def request(self, *args, **kwargs):
        return self.raw.request(*args, **kwargs)

    def post(self, path: str, *, content=b"", headers=None, **kwargs):
        headers = headers or {}
        if "?" in path or "origin" in {key.lower() for key in headers} or "x-forwarded-host" in {
            key.lower() for key in headers
        }:
            return self.raw.post(path, content=content, headers=headers, **kwargs)
        if not path.startswith("/v1/app/"):
            return self.raw.post(path, content=content, headers=headers, **kwargs)
        return self.secure_post(path, content, headers=headers)

    def request_envelope(self, envelope: bytes):
        return self.raw.post(ENVELOPE_ROUTE, content=envelope, headers=ENVELOPE_HEADERS)

    def seal_request(self, path: str, body: bytes, *, nonce: bytes | None = None, version: int = ENVELOPE_VERSION):
        if nonce is None:
            self.sequence += 1
            nonce = self.sequence.to_bytes(8, "big") + bytes(8)
        path_bytes = path.encode("ascii")
        plaintext = (
            bytes([version, 1])
            + len(path_bytes).to_bytes(2, "big")
            + len(body).to_bytes(4, "big")
            + path_bytes
            + body
        )
        return _seal_application_envelope(self.identity, b"request", nonce, plaintext)

    def secure_post(self, path: str, body: bytes, *, headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        envelope = self.seal_request(path, body)
        outer = self.request_envelope(envelope)
        if outer.status_code != 200:
            return outer
        try:
            nonce, plaintext = _open_application_envelope(
                self.identity, b"response", outer.content
            )
        except ValueError:
            return httpx.Response(502, content=b"response authentication failed")
        status = int.from_bytes(plaintext[1:3], "big")
        body_length = int.from_bytes(plaintext[3:7], "big")
        if plaintext[0] != ENVELOPE_VERSION or len(plaintext) != 7 + body_length:
            return httpx.Response(502, content=b"response frame invalid")
        return httpx.Response(
            status,
            content=plaintext[7:],
            request=httpx.Request("POST", f"http://jarvis.local{path}"),
        )


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
        yield AuthenticatedNativeTestClient(client, identity)
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
    assert int(result["expires_at_epoch_us"]) > time.time_ns() // 1000
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
    assert int(grant_fields["expires_at_epoch_us"]) > time.time_ns() // 1000
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
    ).status_code == 404
    assert native_client.post(
        "/v1/app/missions/list",
        content=body(session_token="x" * 43, domain_id="dom_synthetic_a"),
        headers={**HEADERS, "x-forwarded-host": "jarvis.local"},
    ).status_code == 404
    oversized = "x" * 1025
    assert native_client.post(
        "/v1/app/session/open",
        content=oversized,
        headers=HEADERS,
    ).status_code == 413


def test_native_protocol_requires_encrypted_authenticated_v3_and_replay_rejection(native_client):
    plain = native_client.raw.post(
        "/v1/app/session/open",
        content=body(passphrase=PASSPHRASE),
        headers=HEADERS,
    )
    assert plain.status_code == 404

    forged = native_client.request_envelope(b"not-an-authenticated-envelope")
    assert forged.status_code == 401

    stale_identity = NativeRuntimeIdentity(
        instance_id=native_client.identity.instance_id,
        secret=bytearray(b"x" * 32),
        directory_dev=1,
        directory_ino=1,
    )
    stale = AuthenticatedNativeTestClient(native_client.raw, stale_identity)
    stale_response = stale.request_envelope(
        stale.seal_request("/v1/app/session/open", body(passphrase="credencial-sintetica-incorreta").encode())
    )
    assert stale_response.status_code == 401
    stale_identity.clear()

    old_generation = NativeRuntimeIdentity(
        instance_id="test-generation-old",
        secret=bytearray(native_client.identity.secret),
        directory_dev=1,
        directory_ino=1,
    )
    old_client = AuthenticatedNativeTestClient(native_client.raw, old_generation)
    old_response = old_client.request_envelope(
        old_client.seal_request(
            "/v1/app/session/open",
            body(passphrase="credencial-sintetica-incorreta").encode(),
        )
    )
    assert old_response.status_code == 401
    old_generation.clear()

    nonce = (1).to_bytes(8, "big") + bytes(8)
    envelope = native_client.seal_request(
        "/v1/app/session/open",
        body(passphrase="credencial-sintetica-incorreta").encode(),
        nonce=nonce,
    )
    first = native_client.request_envelope(envelope)
    assert first.status_code == 200
    _, response_plaintext = _open_application_envelope(
        native_client.identity, b"response", first.content
    )
    assert fields(httpx.Response(200, content=response_plaintext[7:]))["code"] == "credential_rejected"
    replayed = native_client.request_envelope(envelope)
    assert replayed.status_code == 409


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
    replayed = call("grants/mission-read", session_token=s2, csrf_token=csrf2, domain_id="dom_synthetic_a")
    assert replayed["ok"] == "true" and replayed["grant_id"] == g2["grant_id"]
    assert replayed["expires_at"] == g2["expires_at"]
    assert replayed["expires_at_epoch_us"] == g2["expires_at_epoch_us"]
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


@pytest.mark.parametrize("offset_us", [-750_000, -1, 0])
def test_fractional_grant_expiry_and_reconsent_match_authoritative_deadline(native_client, monkeypatch, offset_us):
    from datetime import timedelta, timezone
    import local_security as security
    from native_app_api import _epoch_microseconds

    instant = datetime(2026, 10, 7, 12, 0, 0, 750_000, tzinfo=timezone.utc)
    monkeypatch.setattr(security, "_now", lambda: instant)
    monkeypatch.setattr("native_app_api._now", lambda: instant)

    def call(path, **values):
        return fields(native_client.post("/v1/app/" + path, content=body(**values), headers=HEADERS))

    opened = call("session/open", passphrase=PASSPHRASE)
    token, csrf = opened["session_token"], opened["csrf_token"]
    assert int(opened["expires_at_epoch_us"]) == _epoch_microseconds(datetime.fromisoformat(opened["expires_at"]))
    assert int(opened["expires_at_epoch_us"]) % 1_000_000 == 750_000
    MissionRepository(native_client.app.state.memory_store).create(
        "owner", "Missão temporal sintética", "dom_synthetic_a", "mac00311-temporal-seed")
    first = call("grants/mission-read", session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a")
    deadline = datetime.fromisoformat(first["expires_at"])
    transmitted = int(first["expires_at_epoch_us"])
    assert transmitted == _epoch_microseconds(deadline)
    assert transmitted % 1_000_000 == 750_000
    assert "expires_at_epoch" not in first

    instant = deadline + timedelta(microseconds=offset_us)
    # Same integer comparison as Rust's cache; precision matches the server.
    cache_expired = transmitted <= _epoch_microseconds(instant)
    read = call("missions/list", session_token=token, domain_id="dom_synthetic_a")
    renewed = call("grants/mission-read", session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a")
    if offset_us < 0:
        assert not cache_expired
        assert read["ok"] == "true" and read["title"] == "Missão temporal sintética"
        assert renewed["ok"] == "true"
        assert renewed["grant_id"] == first["grant_id"]
        assert renewed["expires_at_epoch_us"] == first["expires_at_epoch_us"]
    else:
        assert cache_expired
        assert read == {"ok": "false", "code": "grant_required"}
        assert renewed["ok"] == "true"
        assert renewed["grant_id"] != first["grant_id"]
        assert call("missions/list", session_token=token, domain_id="dom_synthetic_a")["ok"] == "true"


def test_lost_grant_response_replays_exact_scope_without_extending_it(native_client):
    from datetime import timedelta
    import local_security as security

    token, csrf = login(native_client)
    created = fields(native_client.post("/v1/app/grants/mission-read", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a"), headers=HEADERS))
    retried = fields(native_client.post("/v1/app/grants/mission-read", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a"), headers=HEADERS))
    assert retried["grant_id"] == created["grant_id"]
    assert retried["expires_at_epoch_us"] == created["expires_at_epoch_us"]
    active = [grant for grant in security._grants.values() if not grant.revoked]
    assert len(active) == 1

    security._grants[created["grant_id"]].revoked = True
    wider = security.GrantIn(
        connector="mission_sim",
        permission="read",
        resource_ids=["mission:read"],
        domain_ids=["dom_synthetic_a", "dom_synthetic_b"],
        expires_at=security._now() + timedelta(minutes=10),
    )
    security._create_grant_for_session(security._native_session(token, csrf, mutation=True), wider)
    overlap = fields(native_client.post("/v1/app/grants/mission-read", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a"), headers=HEADERS))
    assert overlap == {"ok": "false", "code": "grant_conflict"}


def test_native_capture_persists_for_the_session_and_does_not_open_a_mission(native_client):
    denied = fields(native_client.post("/v1/app/captures/list", content=body(session_token=""), headers=HEADERS))
    assert denied == {"ok": "false", "code": "session_required"}
    token, csrf = login(native_client)
    empty = fields(native_client.post("/v1/app/captures/list", content=body(session_token=token), headers=HEADERS))
    assert empty == {"ok": "true", "count": "0", "items": ""}
    saved = fields(native_client.post("/v1/app/captures/create", content=body(
        session_token=token, csrf_token=csrf, text="Ideia sintética do dia"), headers=HEADERS))
    assert saved["ok"] == "true" and saved["domain_id"] == "dom_synthetic_a"
    listed = fields(native_client.post("/v1/app/captures/list", content=body(session_token=token), headers=HEADERS))
    assert listed["count"] == "1"
    assert listed["items"] == f"{saved['id']}\t{saved['created_at']}\tIdeia sintética do dia"
    missions = fields(native_client.post("/v1/app/missions/list", content=body(
        session_token=token, domain_id="dom_synthetic_a"), headers=HEADERS))
    assert missions == {"ok": "false", "code": "grant_required"}
    rejected = fields(native_client.post("/v1/app/captures/create", content=body(
        session_token=token, csrf_token=csrf, text="linha\nexterna"), headers=HEADERS))
    assert rejected == {"ok": "false", "code": "capture_rejected"}
    cleared = fields(native_client.post("/v1/app/captures/clear", content=body(
        session_token=token, csrf_token=csrf), headers=HEADERS))
    assert cleared == {"ok": "true", "cleared": "true"}
    after = fields(native_client.post("/v1/app/captures/list", content=body(session_token=token), headers=HEADERS))
    assert after["count"] == "0"


def test_connector_status_stays_disconnected_without_printing_client_id(native_client, monkeypatch):
    token, _csrf = login(native_client)
    monkeypatch.delenv("JARVIS_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    missing = fields(native_client.post(
        "/v1/app/connectors/status", content=body(session_token=token), headers=HEADERS))
    assert missing["gmail"] == "not_connected"
    assert missing["gmail_block"] == "missing_oauth_client"
    assert missing["calendar"] == "not_connected"
    assert missing["calendar_sim"] == "synthetic_local"
    assert missing["gmail_scope"] == "gmail.readonly"
    monkeypatch.setenv("JARVIS_GOOGLE_OAUTH_CLIENT_ID", "synthetic-client-id-not-a-secret-value")
    present = fields(native_client.post(
        "/v1/app/connectors/status", content=body(session_token=token), headers=HEADERS))
    assert present["gmail_block"] == "consent_required"
    assert "synthetic-client-id-not-a-secret-value" not in "".join(present.values())
    from external_connectors import ConnectorUnavailable, read_gmail_messages, read_google_calendar_events
    with pytest.raises(ConnectorUnavailable):
        read_gmail_messages()
    with pytest.raises(ConnectorUnavailable):
        read_google_calendar_events()


def test_review_grant_requires_explicit_confirmation_and_does_not_approve(native_client):
    token, csrf = login(native_client)
    missing = fields(native_client.post("/v1/app/reviews/pending", content=body(
        session_token=token, domain_id="dom_synthetic_a"), headers=HEADERS))
    assert missing == {"ok": "false", "code": "grant_required"}
    refused = fields(native_client.post("/v1/app/grants/mission-review", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a", confirm="no"), headers=HEADERS))
    assert refused == {"ok": "false", "code": "scope_invalid"}
    granted = fields(native_client.post("/v1/app/grants/mission-review", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a", confirm="review-local"), headers=HEADERS))
    assert granted["ok"] == "true" and granted["resource"] == "mission:review"
    replayed = fields(native_client.post("/v1/app/grants/mission-review", content=body(
        session_token=token, csrf_token=csrf, domain_id="dom_synthetic_a", confirm="review-local"), headers=HEADERS))
    assert replayed["grant_id"] == granted["grant_id"]
    pending = fields(native_client.post("/v1/app/reviews/pending", content=body(
        session_token=token, domain_id="dom_synthetic_a"), headers=HEADERS))
    assert pending == {"ok": "true", "count": "0"}
    denied = fields(native_client.post("/v1/app/reviews/approve", content=body(
        session_token=token, csrf_token=csrf, review_id="review_missing_local",
        expected_revision="1", expected_sha="a" * 64, idempotency_key="approve-local-1",
        confirm="approve-local"), headers=HEADERS))
    assert denied == {"ok": "false", "code": "operation_failed"}
    missions = fields(native_client.post("/v1/app/missions/list", content=body(
        session_token=token, domain_id="dom_synthetic_a"), headers=HEADERS))
    assert missions == {"ok": "false", "code": "grant_required"}


def test_epoch_microseconds_preserves_datetime_precision_without_float_rounding():
    from datetime import timezone
    from native_app_api import _epoch_microseconds

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    value = datetime(2026, 10, 7, 12, 0, 0, 750_001, tzinfo=timezone.utc)
    delta = value - epoch
    assert _epoch_microseconds(value) == (delta.days * 86400 + delta.seconds) * 1_000_000 + 750_001
