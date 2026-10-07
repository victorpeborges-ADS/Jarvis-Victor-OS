"""MAC-003's closed, UDS-only G5 application protocol."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote_to_bytes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from domain_registry import MISSION_READ_RESOURCE
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
)
from mission_repository import MissionCorrupt, MissionRepository

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
        grant = _create_grant_for_session(session, body)
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
