"""MAC-003's closed, UDS-only G5 application protocol."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote_to_bytes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from domain_registry import MISSION_READ_RESOURCE, MISSION_REVIEW_RESOURCE
from local_security import (
    GrantIn,
    LoginIn,
    _create_grant_for_session,
    _native_session,
    _now,
    _open_session_for_passphrase,
    _revoke_grant_for_session,
    _close_session_for,
    mission_read_scope_confirmed,
    mission_review_confirmed,
)
from external_connectors import public_status
from local_captures import clear_captures, create_capture, encode_capture_items, list_captures
from mission_repository import MissionConflict, MissionCorrupt, MissionDenied, MissionRejected, MissionRepository

router = APIRouter()
NATIVE_DOMAIN = "dom_synthetic_a"
NATIVE_GRANT_TTL = timedelta(minutes=60)
MAX_REQUEST_BYTES = 1024
MAX_RESPONSE_BYTES = 2048
MAX_PASSPHRASE_BYTES = 128
MAX_MISSION_TITLE = 80
EXPECTED_FIELDS = {
    "/v1/app/session/open": ("passphrase",),
    "/v1/app/session/close": ("session_token", "csrf_token"),
    "/v1/app/grants/mission-read": ("session_token", "csrf_token", "domain_id"),
    "/v1/app/grants/mission-read/revoke": ("session_token", "csrf_token", "grant_id"),
    "/v1/app/missions/list": ("session_token", "domain_id"),
    "/v1/app/captures/create": ("session_token", "csrf_token", "text"),
    "/v1/app/captures/list": ("session_token",),
    "/v1/app/captures/clear": ("session_token", "csrf_token"),
    "/v1/app/connectors/status": ("session_token",),
    "/v1/app/grants/mission-review": ("session_token", "csrf_token", "domain_id", "confirm"),
    "/v1/app/reviews/pending": ("session_token", "domain_id"),
    "/v1/app/reviews/approve": (
        "session_token",
        "csrf_token",
        "review_id",
        "expected_revision",
        "expected_sha",
        "idempotency_key",
        "confirm",
    ),
}


def _decode_value(raw: str) -> str:
    if not raw.isascii() or re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        raise ValueError("valor inválido")
    decoded = unquote_to_bytes(raw).decode("utf-8", errors="strict")
    if quote(decoded, safe="-_.~") != raw:
        raise ValueError("codificação inválida")
    return decoded


def _encode_value(value: object) -> str:
    return quote(str(value), safe="-_.~")


def _epoch_microseconds(value: datetime) -> int:
    """Exact datetime precision; no float timestamp rounding or grace period."""
    delta = value.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


async def _read_fields(request: Request, expected: tuple[str, ...]) -> dict[str, str]:
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES or not body.endswith(b"\n"):
        raise ValueError("corpo inválido")
    try:
        lines = body[:-1].decode("ascii", errors="strict").split("\n")
        fields: dict[str, str] = {}
        names: list[str] = []
        for line in lines:
            name, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[a-z_]+", name) or name in fields:
                raise ValueError("campo inválido")
            fields[name] = _decode_value(value)
            names.append(name)
        if tuple(names) != expected:
            raise ValueError("campos inválidos")
        return fields
    finally:
        # Starlette stores the body on Request; drop our reference promptly.
        body = b""


def _response(fields: tuple[tuple[str, object], ...]) -> PlainTextResponse:
    body = "".join(f"{name}={_encode_value(value)}\n" for name, value in fields).encode("ascii")
    if len(body) > MAX_RESPONSE_BYTES:
        return _error("operation_failed")
    return PlainTextResponse(body, media_type="text/plain", headers={"Cache-Control": "no-store"})


def _success(**fields: object) -> PlainTextResponse:
    return _response((("ok", "true"), *tuple(fields.items())))


def _error(code: str) -> PlainTextResponse:
    allowed = {
        "credential_rejected",
        "session_required",
        "grant_required",
        "grant_active",
        "scope_invalid",
        "grant_conflict",
        "grant_expired",
        "operation_failed",
        "capture_rejected",
    }
    safe_code = code if code in allowed else "operation_failed"
    return _response((("ok", "false"), ("code", safe_code)))


def _error_for(exc: HTTPException) -> PlainTextResponse:
    if exc.status_code == 401:
        code = "credential_rejected" if "credencial" in str(exc.detail) else "session_required"
    elif exc.status_code == 403:
        detail = str(exc.detail)
        code = (
            "grant_required"
            if "concessão" in detail
            else "scope_invalid"
            if "escopo" in detail
            else "session_required"
        )
    elif exc.status_code == 404:
        code = "grant_required" if "concessão" in str(exc.detail) else "session_required"
    elif exc.status_code == 409:
        code = "grant_conflict"
    elif exc.status_code in {400, 422}:
        code = "scope_invalid"
    else:
        code = "operation_failed"
    return _error(code)


@router.post("/v1/app/session/open")
async def open_native_session(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        if len(fields["passphrase"].encode("utf-8")) > MAX_PASSPHRASE_BYTES:
            return _error("credential_rejected")
        credentials = LoginIn(passphrase=fields["passphrase"])
        session = _open_session_for_passphrase(credentials.passphrase, "native-uds")
    except (ValueError, UnicodeError, ValidationError):
        return _error("credential_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(
        principal=session.principal,
        session_token=session.token,
        csrf_token=session.csrf_token,
        expires_at_epoch_us=_epoch_microseconds(session.expires_at),
        expires_at=session.expires_at.isoformat(),
    )


@router.post("/v1/app/session/close")
async def close_native_session(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        _close_session_for(session)
    except (ValueError, UnicodeError):
        return _error("session_required")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(closed="true")


@router.post("/v1/app/grants/mission-read")
async def create_native_mission_read_grant(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        if fields["domain_id"] != NATIVE_DOMAIN:
            return _error("scope_invalid")
        expires_at = (_now() + NATIVE_GRANT_TTL).astimezone(timezone.utc)
        body = GrantIn(
            connector="mission_sim",
            permission="read",
            resource_ids=[MISSION_READ_RESOURCE],
            domain_ids=[NATIVE_DOMAIN],
            expires_at=expires_at,
        )
        grant = _create_grant_for_session(session, body, replay_exact=True)
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(
        grant_id=grant.id,
        domain_id=NATIVE_DOMAIN,
        expires_at_epoch_us=_epoch_microseconds(grant.expires_at),
        expires_at=grant.expires_at.isoformat(),
    )


@router.post("/v1/app/grants/mission-read/revoke")
async def revoke_native_mission_read_grant(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        _revoke_grant_for_session(
            session,
            fields["grant_id"],
            connector="mission_sim",
            resource_id=MISSION_READ_RESOURCE,
            domain_id=NATIVE_DOMAIN,
        )
    except (ValueError, UnicodeError):
        return _error("session_required")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(revoked="true")


@router.post("/v1/app/missions/list")
async def list_native_missions(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        if fields["domain_id"] != NATIVE_DOMAIN:
            return _error("scope_invalid")
        with mission_read_scope_confirmed(session.principal, NATIVE_DOMAIN, session.token) as allowed:
            if allowed != frozenset({NATIVE_DOMAIN}):
                return _error("grant_required")
            page = MissionRepository(request.app.state.memory_store).list_page(
                session.principal, NATIVE_DOMAIN, 1, None, allowed
            )
            if page["corrupt"] or len(page["items"]) > 1:
                return _error("operation_failed")
            if not page["items"]:
                return _success(dataset="api_synthetic", count=0)
            record = page["items"][0]
            mission = record.get("mission")
            if (
                record.get("dataset") != "api_synthetic"
                or not isinstance(mission, dict)
                or mission.get("domain_id") != NATIVE_DOMAIN
                or not isinstance(mission.get("id"), str)
                or not 1 <= len(mission["id"]) <= 128
                or not isinstance(mission.get("title"), str)
                or len(mission["title"]) > MAX_MISSION_TITLE
                or not isinstance(mission.get("status"), str)
                or type(record.get("revision")) is not int
            ):
                return _error("operation_failed")
            return _success(
                dataset="api_synthetic",
                count=1,
                mission_id=mission["id"],
                title=mission["title"],
                domain_id=NATIVE_DOMAIN,
                status=mission["status"],
                revision=record["revision"],
            )
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("grant_required")
    except MissionCorrupt:
        return _error("operation_failed")


@router.post("/v1/app/captures/create")
async def create_native_capture(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        saved = create_capture(request.app.state.memory_store, session.principal, fields["text"], _now())
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(id=saved["id"], created_at=saved["created_at"], domain_id=saved["domain_id"])


@router.post("/v1/app/captures/list")
async def list_native_captures(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        items = list_captures(request.app.state.memory_store, session.principal)
        payload = encode_capture_items(items)
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(count=len(items), items=payload)


@router.post("/v1/app/captures/clear")
async def clear_native_captures(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        clear_captures(request.app.state.memory_store, session.principal)
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(cleared="true")


@router.post("/v1/app/connectors/status")
async def native_connector_status(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        _native_session(fields["session_token"])
        status = public_status()
    except (ValueError, UnicodeError):
        return _error("session_required")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(
        gmail=status["gmail"],
        gmail_block=status["gmail_block"],
        gmail_scope=status["gmail_scope"],
        calendar=status["calendar"],
        calendar_block=status["calendar_block"],
        calendar_scope=status["calendar_scope"],
        calendar_sim=status["calendar_sim"],
    )


def _review_grant(session, domain_id: str, confirm: str):
    if confirm != "review-local" or domain_id != NATIVE_DOMAIN:
        raise ValueError("confirmação ausente")
    expires_at = (_now() + NATIVE_GRANT_TTL).astimezone(timezone.utc)
    body = GrantIn(
        connector="mission_sim",
        permission="read",
        resource_ids=[MISSION_REVIEW_RESOURCE],
        domain_ids=[NATIVE_DOMAIN],
        expires_at=expires_at,
    )
    return _create_grant_for_session(session, body, replay_exact=True)


@router.post("/v1/app/grants/mission-review")
async def create_native_review_grant(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        grant = _review_grant(session, fields["domain_id"], fields["confirm"])
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    return _success(
        grant_id=grant.id,
        domain_id=NATIVE_DOMAIN,
        resource=MISSION_REVIEW_RESOURCE,
        expires_at_epoch_us=_epoch_microseconds(grant.expires_at),
        expires_at=grant.expires_at.isoformat(),
    )


@router.post("/v1/app/reviews/pending")
async def list_native_pending_reviews(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        if fields["domain_id"] != NATIVE_DOMAIN:
            return _error("scope_invalid")
        with mission_review_confirmed(session.principal, NATIVE_DOMAIN, session.token):
            page = MissionRepository(request.app.state.memory_store).list_reviews(
                session.principal, NATIVE_DOMAIN, "pending", 1, None, frozenset({NATIVE_DOMAIN})
            )
        if page["corrupt"]:
            return _error("operation_failed")
        items = page["items"]
        if not items:
            return _success(count=0)
        item = items[0]
        review_id = item.get("id")
        sha = item.get("artifact_sha256")
        revision = item.get("revision")
        title = item.get("artifact_title")
        if (
            not isinstance(review_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", review_id)
            or not isinstance(sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha)
            or type(revision) is not int
            or not isinstance(title, str)
            or not 1 <= len(title) <= 80
        ):
            return _error("operation_failed")
        return _success(count=1, review_id=review_id, revision=revision, sha256=sha, title=title)
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("grant_required")
    except MissionCorrupt:
        return _error("operation_failed")


@router.post("/v1/app/reviews/approve")
async def approve_native_review(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        if fields["confirm"] != "approve-local":
            return _error("scope_invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", fields["expected_sha"]):
            return _error("scope_invalid")
        if not 8 <= len(fields["idempotency_key"]) <= 160:
            return _error("scope_invalid")
        revision = int(fields["expected_revision"])
        if revision < 1:
            return _error("scope_invalid")
        with mission_review_confirmed(session.principal, NATIVE_DOMAIN, session.token):
            record, replayed = MissionRepository(request.app.state.memory_store).decide_review(
                session.principal,
                fields["review_id"],
                "approved",
                revision,
                fields["expected_sha"],
                None,
                fields["idempotency_key"],
                session.token,
            )
        if record.get("domain_id") != NATIVE_DOMAIN:
            return _error("scope_invalid")
        return _success(approved="true", replayed="true" if replayed else "false")
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("grant_required")
    except MissionDenied:
        return _error("grant_required")
    except (MissionConflict, MissionCorrupt, MissionRejected):
        return _error("operation_failed")
