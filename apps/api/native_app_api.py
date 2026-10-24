"""MAC-003's closed, UDS-only G5 application protocol."""

from __future__ import annotations

import asyncio
import json
import hashlib
import re
import sqlite3
import threading
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
    mission_read_confirmed,
    mission_read_scope_confirmed,
    mission_review_confirmed,
    native_session_confirmed,
    native_review_grant_confirmed,
    revoke_native_review_grants,
    reset_state,
)
from external_connectors import public_status
from local_captures import (
    clear_captures,
    create_capture,
    delete_capture,
    encode_capture_items,
    list_captures,
    open_capture,
    search_captures,
    update_capture,
)
from memory_categories import (
    CATEGORIES as MEMORY_CATEGORIES,
    DOMAINS as MEMORY_DOMAINS,
    delete_memory,
    page_memory,
    record_memory,
    revise_memory,
)
from memory_deletions import MemoryRevisionConflict
from local_automations import (
    AutomationError,
    control_automation,
    create_automation,
    get_automation,
    get_run,
    list_automations,
    list_runs,
    update_timezone,
    run_app_worker,
)
from mission_repository import MissionConflict, MissionCorrupt, MissionDenied, MissionRejected, MissionRepository
from memory_store import MemoryStoreError, is_synthetic_temporary_database
from workflow_executor import WorkflowError, WorkflowExecutor, session_binding, workflow_cursor
from conversation_gateway import Budget
from conversation_continuity import open_conversation, conversation_exists
from grounded_read import GroundedRead, encoded_grounded_body
from artifact_store import put_artifact
from skill_registry import Permission, SkillRegistry, canonical_json

router = APIRouter()
NATIVE_DOMAIN = "dom_synthetic_a"
NATIVE_GRANT_TTL = timedelta(minutes=60)
MAX_REQUEST_BYTES = 1024
MAX_RESPONSE_BYTES = 2048
MAX_WORKFLOW_LIST_ITEMS = 4
MAX_PASSPHRASE_BYTES = 128
MAX_MISSION_TITLE = 80
EXPECTED_FIELDS = {
    "/v1/app/storage/unlock": ("database_key",),
    "/v1/app/storage/rotate": ("database_key", "generation", "operation_id", "intent"),
    "/v1/app/storage/rotate-retire": ("from_account",),
    "/v1/app/storage/rotate-finalize": ("database_key", "operation_id"),
    "/v1/app/storage/lock": (),
    "/v1/app/storage/status": (),
    "/v1/app/session/open": ("passphrase",),
    "/v1/app/session/close": ("session_token", "csrf_token"),
    "/v1/app/grants/mission-read": ("session_token", "csrf_token", "domain_id"),
    "/v1/app/grants/mission-read/revoke": ("session_token", "csrf_token", "grant_id"),
    "/v1/app/missions/list": ("session_token", "domain_id"),
    "/v1/app/captures/create": ("session_token", "csrf_token", "text"),
    "/v1/app/captures/edit": ("session_token", "csrf_token", "capture_id", "text"),
    "/v1/app/captures/delete": ("session_token", "csrf_token", "capture_id"),
    "/v1/app/captures/list": ("session_token",),
    "/v1/app/captures/search": ("session_token", "query"),
    "/v1/app/captures/open": ("session_token", "capture_id"),
    "/v1/app/captures/clear": ("session_token", "csrf_token"),
    "/v1/app/memory/page": ("session_token", "category", "domain_id", "offset"),
    "/v1/app/memory/create": ("session_token", "csrf_token", "category", "domain_id", "body", "source_ref"),
    "/v1/app/memory/edit": ("session_token", "csrf_token", "category", "domain_id", "record_id", "body", "expected_revision"),
    "/v1/app/memory/delete": ("session_token", "csrf_token", "category", "domain_id", "record_id", "expected_revision"),
    "/v1/app/conversation/ask": ("session_token", "conversation_id", "question", "domain_id"),
    "/v1/app/conversation/open": ("session_token", "domain_id", "mode"),
    "/v1/app/conversation/cancel": ("session_token", "conversation_id", "domain_id"),
    "/v1/app/artifacts/synthetic-document": ("session_token", "csrf_token"),
    "/v1/app/connectors/status": ("session_token",),
    "/v1/app/grants/mission-review": ("session_token", "csrf_token", "domain_id", "confirm"),
    "/v1/app/grants/mission-review/revoke": ("session_token", "csrf_token", "domain_id", "confirm"),
    "/v1/app/reviews/pending": ("session_token", "domain_id"),
    "/v1/app/reviews/draft": ("session_token", "csrf_token", "confirm"),
    "/v1/app/reviews/detail": (
        "session_token",
        "domain_id",
        "review_id",
        "expected_revision",
        "expected_sha256",
    ),
    "/v1/app/reviews/approve": (
        "session_token",
        "csrf_token",
        "review_id",
        "expected_revision",
        "expected_sha256",
        "idempotency_key",
        "confirm",
    ),
    "/v1/app/workflows/submit": ("session_token", "csrf_token", "tool_id", "arguments_json", "idempotency_key"),
    "/v1/app/workflows/list": ("session_token",),
    "/v1/app/workflows/page": ("session_token", "cursor"),
    "/v1/app/workflows/detail": ("session_token", "task_id"),
    "/v1/app/workflows/approve": ("session_token", "csrf_token", "task_id", "expected_sha256", "confirm"),
    "/v1/app/workflows/execute": ("session_token", "csrf_token", "task_id", "idempotency_key"),
    "/v1/app/workflows/pause": ("session_token", "csrf_token", "task_id"),
    "/v1/app/workflows/resume": ("session_token", "csrf_token", "task_id"),
    "/v1/app/workflows/cancel": ("session_token", "csrf_token", "task_id"),

        "/v1/app/automations/list": ("session_token",),
        "/v1/app/automations/detail": ("session_token", "automation_id"),
        "/v1/app/automations/history": ("session_token", "automation_id"),
        "/v1/app/automations/run": ("session_token", "automation_id", "run_id"),
        "/v1/app/automations/create": (
        "session_token", "csrf_token", "kind", "title", "recurrence", "local_schedule",
        "timezone", "quiet_start", "quiet_end", "message", "sources_confirmed",
    ),
        "/v1/app/automations/timezone": (
        "session_token", "csrf_token", "automation_id", "timezone",
    ),
        "/v1/app/automations/control": (
        "session_token", "csrf_token", "automation_id", "action", "run_id",
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
    if not body and not expected:
        return {}
    if len(body) > MAX_REQUEST_BYTES or not body.endswith(b"\n"):
        raise ValueError("corpo inválido")
    try:
        lines = body[:-1].decode("ascii", errors="strict").split("\n")
        fields: dict[str, str] = {}
        names: list[str] = []
        for line in lines:
            name, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in fields:
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
        "automation_invalid", "automation_not_found", "automation_limit",
        "automation_conflict", "authorization_required",
        "workflow_rejected",
        "recommendation_rejected", "tool_blocked", "schema_rejected", "limit_exceeded",
        "idempotency_key_rejected", "idempotency_conflict", "owner_rejected", "clock_rejected",
        "task_not_found", "task_corrupt", "state_rejected", "approval_not_required",
        "approval_required", "approval_rejected", "approval_replayed", "approval_expired",
        "parameters_changed", "result_corrupt", "retry_exhausted", "timeout",
        "storage_locked", "storage_unlock_failed", "storage_rotation_blocked",
        "memory_rejected", "memory_conflict",
    }
    safe_code = code if code in allowed else "operation_failed"
    return _response((("ok", "false"), ("code", safe_code)))


@router.post("/v1/app/storage/status")
async def storage_status(request: Request) -> PlainTextResponse:
    try:
        await _read_fields(request, EXPECTED_FIELDS[request.url.path])
    except (ValueError, UnicodeError):
        return _error("operation_failed")
    store = request.app.state.memory_store
    return _success(state="unlocked" if store.is_unlocked else "locked")


@router.post("/v1/app/storage/unlock")
async def storage_unlock(request: Request) -> PlainTextResponse:
    key = bytearray()
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        encoded = fields["database_key"]
        if len(encoded) != 64 or re.fullmatch(r"[0-9a-f]{64}", encoded) is None:
            return _error("storage_unlock_failed")
        key.extend(bytes.fromhex(encoded))
        fields.clear()
        store = request.app.state.memory_store
        if not is_synthetic_temporary_database(store.path):
            return _error("storage_unlock_failed")
        async with request.app.state.storage_lifecycle_lock:
            if store.is_unlocked:
                return _success(state="unlocked")
            store.unlock(key)
            from mission_engine import recover_interrupted
            from source_admission import reconcile_legacy_selected_sources

            reconcile_legacy_selected_sources(store)
            recover_interrupted(store)
            WorkflowExecutor(store).recover(_now())
            scheduler = request.app.state.local_automation_scheduler
            request.app.state.storage_worker = asyncio.create_task(run_app_worker(scheduler))
    except Exception:
        store = request.app.state.memory_store
        store.lock()
        reset_state()
        scheduler = getattr(request.app.state, "local_automation_scheduler", None)
        if scheduler is not None:
            scheduler.clear_session()
        return _error("storage_unlock_failed")
    finally:
        key[:] = b"\x00" * len(key)
    return _success(state="unlocked")


@router.post("/v1/app/storage/lock")
async def storage_lock(request: Request) -> PlainTextResponse:
    try:
        await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        async with request.app.state.storage_lifecycle_lock:
            worker = request.app.state.storage_worker
            if worker is not None:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                request.app.state.storage_worker = None
            request.app.state.conversation_gateway.clear_all()
            with request.app.state.conversation_cancellation_lock:
                for cancellation in request.app.state.conversation_cancellations.values():
                    cancellation.set()
                request.app.state.conversation_cancellations.clear()
            request.app.state.memory_store.lock()
            reset_state()
            scheduler = getattr(request.app.state, "local_automation_scheduler", None)
            if scheduler is not None:
                scheduler.clear_session()
    except (ValueError, UnicodeError):
        return _error("operation_failed")
    except Exception:
        return _error("operation_failed")
    return _success(state="locked")


@router.post("/v1/app/storage/rotate")
async def storage_rotate(request: Request) -> PlainTextResponse:
    key = bytearray()
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        encoded = fields["database_key"]
        generation = fields["generation"]
        operation_id = fields["operation_id"]
        intent = fields["intent"]
        if len(encoded) != 64 or re.fullmatch(r"[0-9a-f]{64}", encoded) is None:
            return _error("storage_rotation_blocked")
        if re.fullmatch(r"gen-v1-[0-9a-f]{32}", generation) is None:
            return _error("storage_rotation_blocked")
        if re.fullmatch(r"[0-9a-f]{64}", operation_id) is None or intent not in {"begin", "resume"}:
            return _error("storage_rotation_blocked")
        key.extend(bytes.fromhex(encoded))
        fields.clear()
        store = request.app.state.memory_store
        if not is_synthetic_temporary_database(store.path) or not store.is_unlocked:
            return _error("storage_rotation_blocked")
        async with request.app.state.storage_lifecycle_lock:
            result = await asyncio.to_thread(
                store.rotate_storage_key, bytes(key), generation, operation_id, intent,
            )
        if result.cleanup not in {"pending", "complete"} or result.phase not in {
            "validated", "committed", "finalized",
        }:
            return _error("storage_rotation_blocked")
        state = result.phase
        if result.retire_account and re.fullmatch(r"primary|gen-v1-[0-9a-f]{32}", result.retire_account) is None:
            return _error("storage_rotation_blocked")
    except Exception:
        return _error("storage_rotation_blocked")
    finally:
        key[:] = b"\x00" * len(key)
    return _success(
        state=state, retire_account=result.retire_account, operation_id=result.operation_id,
        cleanup=result.cleanup,
    )


@router.post("/v1/app/storage/rotate-retire")
async def storage_rotate_retire(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        from_account = fields["from_account"]
        if re.fullmatch(r"primary|gen-v1-[0-9a-f]{32}", from_account) is None:
            return _error("storage_rotation_blocked")
        store = request.app.state.memory_store
        if not is_synthetic_temporary_database(store.path) or not store.is_unlocked:
            return _error("storage_rotation_blocked")
        async with request.app.state.storage_lifecycle_lock:
            await asyncio.to_thread(store.mark_storage_key_retired, from_account)
    except Exception:
        return _error("storage_rotation_blocked")
    return _success(state="committed")


@router.post("/v1/app/storage/rotate-finalize")
async def storage_rotate_finalize(request: Request) -> PlainTextResponse:
    key = bytearray()
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        encoded = fields["database_key"]
        operation_id = fields["operation_id"]
        if len(encoded) != 64 or re.fullmatch(r"[0-9a-f]{64}", encoded) is None:
            return _error("storage_rotation_blocked")
        if re.fullmatch(r"[0-9a-f]{64}", operation_id) is None:
            return _error("storage_rotation_blocked")
        key.extend(bytes.fromhex(encoded))
        fields.clear()
        store = request.app.state.memory_store
        if not is_synthetic_temporary_database(store.path) or not store.is_unlocked:
            return _error("storage_rotation_blocked")
        async with request.app.state.storage_lifecycle_lock:
            result = await asyncio.to_thread(store.finalize_storage_key, operation_id)
        if result.phase != "finalized" or result.operation_id != operation_id:
            return _error("storage_rotation_blocked")
    except Exception:
        return _error("storage_rotation_blocked")
    finally:
        key[:] = b"\x00" * len(key)
    return _success(state="finalized", operation_id=operation_id, cleanup="complete")


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
        scheduler = getattr(request.app.state, "local_automation_scheduler", None)
        if scheduler is not None:
            scheduler.set_session(session.token)
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
        request.app.state.conversation_gateway.retire_session(session.token)
        with request.app.state.conversation_cancellation_lock:
            stale_keys = [
                key for key in request.app.state.conversation_cancellations
                if key[0] == session.token
            ]
            for key in stale_keys:
                request.app.state.conversation_cancellations.pop(key).set()
        _close_session_for(session)
        scheduler = getattr(request.app.state, "local_automation_scheduler", None)
        if scheduler is not None:
            scheduler.clear_session(session.token)
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
        if session.principal != "owner" or fields["domain_id"] != NATIVE_DOMAIN:
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
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(id=saved["id"], created_at=saved["created_at"], domain_id=saved["domain_id"])


@router.post("/v1/app/captures/edit")
async def edit_native_capture(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        saved = update_capture(
            request.app.state.memory_store, session.principal, fields["capture_id"], fields["text"]
        )
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(id=saved["id"], created_at=saved["created_at"], domain_id=saved["domain_id"])


@router.post("/v1/app/captures/delete")
async def delete_native_capture(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        delete_capture(request.app.state.memory_store, session.principal, fields["capture_id"])
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(deleted="true")


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
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(count=len(items), items=payload)


def _memory_fields(item: dict[str, str | int]) -> dict[str, object]:
    return {key: item[key] for key in (
        "id", "category", "domain_id", "body", "source_kind", "source_ref",
        "version", "recorded_at", "revised_at",
    )}


def _memory_record_json(item: dict[str, str | int]) -> str:
    return json.dumps(_memory_fields(item), ensure_ascii=False, separators=(",", ":"))


@router.post("/v1/app/memory/page")
async def page_native_memory(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        category, domain = fields["category"], fields["domain_id"]
        offset = int(fields["offset"])
        if category not in {"explicit_capture", *MEMORY_CATEGORIES} or domain not in MEMORY_DOMAINS:
            raise ValueError("memória recusada")
        item = page_memory(request.app.state.memory_store, session.principal, domain, category, offset)
    except (ValueError, UnicodeError):
        return _error("memory_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    if item is None:
        return _success(has_item="false")
    return _success(has_item="true", record=_memory_record_json(item))


@router.post("/v1/app/memory/create")
async def create_native_memory(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        category, domain = fields["category"], fields["domain_id"]
        if category == "explicit_capture":
            if domain != "dom_synthetic_a" or fields["source_ref"] != "explicit_capture":
                raise ValueError("memória recusada")
            saved = create_capture(request.app.state.memory_store, session.principal, fields["body"], _now())
            item = {
                "id": saved["id"], "category": category, "domain_id": domain, "body": fields["body"],
                "source_kind": "user_authored_capture", "source_ref": "explicit_capture", "version": 1,
                "recorded_at": saved["created_at"], "revised_at": saved["created_at"],
            }
        else:
            expected = MEMORY_CATEGORIES.get(category)
            if expected is None:
                raise ValueError("memória recusada")
            item = record_memory(
                request.app.state.memory_store, session.principal, domain, category, fields["body"],
                expected[1], fields["source_ref"], _now(),
            )
    except MemoryRevisionConflict:
        return _error("memory_conflict")
    except (ValueError, UnicodeError):
        return _error("memory_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(record=_memory_record_json(item))


@router.post("/v1/app/memory/edit")
async def edit_native_memory(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        expected_revision = int(fields["expected_revision"])
        if not 1 <= expected_revision <= 2**31 - 1:
            raise ValueError("memória recusada")
        category, domain, record_id = fields["category"], fields["domain_id"], fields["record_id"]
        if category == "explicit_capture":
            if domain != "dom_synthetic_a":
                raise ValueError("memória recusada")
            saved = update_capture(
                request.app.state.memory_store, session.principal, record_id, fields["body"], expected_revision,
            )
            item = {
                "id": record_id, "category": category, "domain_id": domain, "body": fields["body"],
                "source_kind": "user_authored_capture", "source_ref": "explicit_capture",
                "version": saved["version"], "recorded_at": saved["created_at"], "revised_at": saved["revised_at"],
            }
        else:
            item = revise_memory(
                request.app.state.memory_store, session.principal, domain, category, record_id,
                fields["body"], _now(), expected_revision,
            )
    except MemoryRevisionConflict:
        return _error("memory_conflict")
    except (ValueError, UnicodeError):
        return _error("memory_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(record=_memory_record_json(item))


@router.post("/v1/app/memory/delete")
async def delete_native_memory(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        expected_revision = int(fields["expected_revision"])
        if not 1 <= expected_revision <= 2**31 - 1:
            raise ValueError("memória recusada")
        category, domain, record_id = fields["category"], fields["domain_id"], fields["record_id"]
        if category == "explicit_capture":
            if domain != "dom_synthetic_a":
                raise ValueError("memória recusada")
            deleted = delete_capture(request.app.state.memory_store, session.principal, record_id, expected_revision)
        else:
            deleted = delete_memory(
                request.app.state.memory_store, session.principal, domain, category, record_id, expected_revision,
            )
    except MemoryRevisionConflict:
        return _error("memory_conflict")
    except (ValueError, UnicodeError):
        return _error("memory_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(deleted="true", deleted_revision=deleted.get("deleted_revision", expected_revision),
                    operation_id=deleted.get("operation_id", ""))


@router.post("/v1/app/captures/search")
async def search_native_captures(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        items, omitted = search_captures(
            request.app.state.memory_store, session.principal, fields["query"]
        )
        payload = encode_capture_items(items)
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(count=len(items), omitted=omitted, items=payload)


@router.post("/v1/app/captures/open")
async def open_native_capture(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        opened = open_capture(request.app.state.memory_store, session.principal, fields["capture_id"])
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(
        id=opened["id"],
        created_at=opened["created_at"],
        domain_id=opened["domain_id"],
        category=opened["category"],
        text=opened["text"],
    )


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
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(cleared="true")


@router.post("/v1/app/conversation/ask")
async def ask_native_conversation(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        if session.principal != "owner" or fields["domain_id"] != NATIVE_DOMAIN:
            return _error("scope_invalid")
        cancellation_key = (session.token, fields["conversation_id"])
        cancellation = threading.Event()
        with request.app.state.conversation_cancellation_lock:
            previous = request.app.state.conversation_cancellations.get(cancellation_key)
            if previous is not None:
                previous.set()
            request.app.state.conversation_cancellations[cancellation_key] = cancellation
        def run_read():
            with request.app.state.grounded_read_lock:
                registry = getattr(request.app.state, "skill_registry", None)
                manifest_sha256 = (
                    registry.trusted_manifest_sha256("generate-synthetic-document")
                    if isinstance(registry, SkillRegistry) else ""
                )
                reader = GroundedRead(
                    request.app.state.conversation_gateway,
                    request.app.state.memory_store,
                    request.app.state.grounded_documents,
                    lambda text: request.app.state.grounded_reply.__setitem__("text", text),
                    manifest_sha256=manifest_sha256,
                )
                return reader.ask(
                    fields["session_token"],
                    {
                        "conversation_id": fields["conversation_id"],
                        "question": fields["question"],
                        "domain_id": fields["domain_id"],
                    },
                    Budget(max_seconds=2.0, max_tokens=64, max_attempts=1, max_calls=1, max_identical=1),
                    cancel_event=cancellation,
                )

        try:
            result = await asyncio.to_thread(run_read)
        finally:
            with request.app.state.conversation_cancellation_lock:
                if request.app.state.conversation_cancellations.get(cancellation_key) is cancellation:
                    request.app.state.conversation_cancellations.pop(cancellation_key, None)
        if result.status == "session_required":
            return _error("session_required")
        if result.status == "invalid_request":
            return _error("capture_rejected")
        if session.principal != "owner":
            return _error("scope_invalid")
        body = encoded_grounded_body(
            status=result.status,
            reason=result.reason,
            provider_id=request.app.state.conversation_gateway._provider.provider_id,
            cost="unmeasured",
            text=result.text,
            omitted=result.omitted,
            sources=result.sources,
        )
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    if len(body) > MAX_RESPONSE_BYTES:
        return _error("operation_failed")
    return PlainTextResponse(body, media_type="text/plain", headers={"Cache-Control": "no-store"})


@router.post("/v1/app/conversation/open")
async def open_native_conversation(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        if session.principal != "owner" or fields["domain_id"] != NATIVE_DOMAIN:
            return _error("scope_invalid")
        if fields["mode"] not in {"new", "resume"}:
            return _error("capture_rejected")
        result = open_conversation(
            request.app.state.memory_store,
            session.principal,
            NATIVE_DOMAIN,
            fields["mode"],
            _now(),
        )
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(conversation_id=result["conversation_id"], expires_at=result["expires_at"])


@router.post("/v1/app/conversation/cancel")
async def cancel_native_conversation(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        if session.principal != "owner" or fields["domain_id"] != NATIVE_DOMAIN:
            return _error("scope_invalid")
        if not conversation_exists(
            request.app.state.memory_store,
            session.principal,
            NATIVE_DOMAIN,
            fields["conversation_id"],
            _now(),
        ):
            return _error("capture_rejected")
        cancellation_key = (session.token, fields["conversation_id"])
        with request.app.state.conversation_cancellation_lock:
            cancellation = request.app.state.conversation_cancellations.get(cancellation_key)
            if cancellation is not None:
                cancellation.set()
        request.app.state.conversation_gateway.cancel(session.token, fields["conversation_id"])
    except (ValueError, UnicodeError):
        return _error("capture_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
    return _success(cancelled="true")


@router.post("/v1/app/artifacts/synthetic-document")
async def generate_native_synthetic_document(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        registry = getattr(request.app.state, "skill_registry", None)
        if not isinstance(registry, SkillRegistry):
            return _error("operation_failed")
        result = registry.run(
            "generate-synthetic-document",
            {
                "title": "Resumo sintético de exemplo",
                "sections": [{
                    "heading": "Conteúdo de teste",
                    "paragraphs": ["Este documento contém somente texto sintético local."],
                    "source_id": "src_exemplo_sintetico",
                }],
            },
            Permission("generate_synthetic_document", "synthetic", session.principal),
        )
        if not result.ok or result.artifact is None:
            return _error("operation_failed")
        artifact_json = canonical_json(result.artifact)
        from datetime import timedelta
        manifest_hash = registry.trusted_manifest_sha256("generate-synthetic-document")
        stored = put_artifact(
            request.app.state.memory_store,
            session.principal,
            NATIVE_DOMAIN,
            artifact_json.encode("utf-8"),
            _now(),
            _now() + timedelta(hours=24),
            manifest_sha256=manifest_hash,
        )
        if stored["sha256"] != hashlib.sha256(artifact_json.encode("utf-8")).hexdigest():
            return _error("operation_failed")
        response = _success(artifact_json=artifact_json, artifact_sha256=stored["sha256"])
    except (ValueError, UnicodeError):
        return _error("schema_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except (OSError, sqlite3.Error):
        return _error("operation_failed")
    if len(response.body) > MAX_RESPONSE_BYTES:
        return _error("operation_failed")
    return response


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


@router.post("/v1/app/grants/mission-review/revoke")
async def revoke_native_review_grant(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        if fields["domain_id"] != NATIVE_DOMAIN or fields["confirm"] != "revoke-review-local":
            return _error("scope_invalid")
        count = revoke_native_review_grants(session.token)
        return _success(revoked="true", count=count)
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("session_required")


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


@router.post("/v1/app/reviews/draft")
async def queue_native_review_draft(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        if fields["confirm"] != "draft-local":
            return _error("scope_invalid")
        with mission_review_confirmed(session.principal, NATIVE_DOMAIN, session.token):
            repo = MissionRepository(request.app.state.memory_store)
            page = repo.list_reviews(session.principal, NATIVE_DOMAIN, "pending", 1, None, frozenset({NATIVE_DOMAIN}))
            if page["corrupt"]:
                return _error("operation_failed")
            if page["items"]:
                return _success(queued="false")
            record, _replayed = repo.create(
                session.principal,
                "Rascunho sintético local",
                NATIVE_DOMAIN,
                "draft-local-fixed",
            )
            mission = record["mission"]
            now = mission["created_at"]
            artifact = repo._draft_artifact(
                mission,
                now,
                "report",
                "Rascunho sintético local",
                "Rascunho determinístico aguardando revisão humana. Nenhuma aprovação foi marcada.",
            )
            mission["artifacts"].append(artifact)
            with request.app.state.memory_store.transaction() as connection:
                repo._sync_artifact_review(connection, mission, session.principal, artifact, now)
                connection.execute(
                    "UPDATE missions SET document_json=?, updated_at=? WHERE id=? AND owner=?",
                    (json.dumps(mission, ensure_ascii=False), now, mission["id"], session.principal),
                )
        return _success(queued="true")
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("grant_required")
    except (MissionConflict, MissionCorrupt, MissionRejected):
        return _error("operation_failed")


@router.post("/v1/app/reviews/detail")
async def read_native_review_detail(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        if fields["domain_id"] != NATIVE_DOMAIN:
            return _error("scope_invalid")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", fields["review_id"]):
            return _error("scope_invalid")
        if not re.fullmatch(r"[1-9][0-9]{0,15}", fields["expected_revision"]):
            return _error("scope_invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", fields["expected_sha256"]):
            return _error("scope_invalid")
        expected_revision = int(fields["expected_revision"])
        if expected_revision > 9_007_199_254_740_991:
            return _error("scope_invalid")
        with mission_review_confirmed(session.principal, NATIVE_DOMAIN, session.token):
            review = MissionRepository(request.app.state.memory_store).get_review(
                session.principal, fields["review_id"]
            )
        if (
            review is None
            or review.get("domain_id") != NATIVE_DOMAIN
            or review.get("state") != "pending"
            or review.get("content_withheld") is not False
            or review.get("classification") is not None
            or review.get("revision") != expected_revision
            or review.get("artifact_sha256") != fields["expected_sha256"]
        ):
            return _error("operation_failed")
        artifact = review.get("artifact")
        if not isinstance(artifact, dict):
            return _error("operation_failed")
        title = artifact.get("title")
        content = artifact.get("content")
        if (
            not isinstance(title, str)
            or not 1 <= len(title) <= MAX_MISSION_TITLE
            or any(ord(character) < 32 or ord(character) == 127 for character in title)
            or not isinstance(content, str)
            or not content
            or any(
                (ord(character) < 32 and character not in "\n\t") or ord(character) == 127
                for character in content
            )
        ):
            return _error("operation_failed")
        return _success(
            review_id=fields["review_id"],
            revision=expected_revision,
            sha256=fields["expected_sha256"],
            title=title,
            content=content,
        )
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except (PermissionError, MissionDenied):
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
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", fields["review_id"]):
            return _error("scope_invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", fields["expected_sha256"]):
            return _error("scope_invalid")
        if not 8 <= len(fields["idempotency_key"]) <= 160:
            return _error("scope_invalid")
        if not re.fullmatch(r"[1-9][0-9]{0,15}", fields["expected_revision"]):
            return _error("scope_invalid")
        revision = int(fields["expected_revision"])
        if revision > 9_007_199_254_740_991:
            return _error("scope_invalid")
        with mission_review_confirmed(session.principal, NATIVE_DOMAIN, session.token):
            record, replayed = MissionRepository(request.app.state.memory_store).decide_review(
                session.principal,
                fields["review_id"],
                "approved",
                revision,
                fields["expected_sha256"],
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


def _workflow_error(exc: WorkflowError) -> PlainTextResponse:
    return _error(exc.code)


@router.post("/v1/app/workflows/submit")
async def submit_native_workflow(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        if len(fields["arguments_json"].encode("utf-8")) > 700:
            return _error("limit_exceeded")
        recommendation = {"tool_id": fields["tool_id"], "arguments": json.loads(fields["arguments_json"])}
        with native_session_confirmed(session.token) as current:
            task = WorkflowExecutor(request.app.state.memory_store).submit(
                current.principal, recommendation, fields["idempotency_key"], _now()
            )
        return _success(task_json=json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("session_required")
    except WorkflowError as exc:
        return _workflow_error(exc)


@router.post("/v1/app/workflows/list")
async def list_native_workflows(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        with native_session_confirmed(session.token) as current:
            tasks = WorkflowExecutor(request.app.state.memory_store).list_tasks(
                current.principal, _now(), limit=MAX_WORKFLOW_LIST_ITEMS
            )
        return _success(tasks_json=json.dumps(tasks, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (ValueError, UnicodeError):
        return _error("session_required")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("session_required")
    except WorkflowError as exc:
        return _workflow_error(exc)


# 256 bytes reserved for MAC-003 framing (7), nonce/tag (48), and margin.
# The existing list contract and global transport limits are unchanged.
WORKFLOW_PAGE_BODY_BYTES = 1792


def _workflow_page_response(tasks: list[dict], has_more: bool) -> PlainTextResponse:
    for count in range(len(tasks), 0, -1):
        selected = tasks[:count]
        cursor = workflow_cursor(selected[-1]) if has_more or count < len(tasks) else ""
        response = _success(
            tasks_json=json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            next_cursor=cursor,
        )
        # _response's oversized fallback is not a successful page.
        if response.body.startswith(b"ok=true\n") and len(response.body) <= WORKFLOW_PAGE_BODY_BYTES:
            return response
    if tasks:
        return _error("limit_exceeded")  # Never skip or truncate an oversized item.
    return _success(tasks_json="[]", next_cursor="")


@router.post("/v1/app/workflows/page")
async def page_native_workflows(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        with native_session_confirmed(session.token) as current:
            tasks, has_more = WorkflowExecutor(request.app.state.memory_store).page_tasks(
                current.principal, _now(), fields["cursor"]
            )
        return _workflow_page_response(tasks, has_more)
    except (ValueError, UnicodeError):
        return _error("schema_rejected")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("session_required")
    except WorkflowError as exc:
        return _workflow_error(exc)


@router.post("/v1/app/workflows/detail")
async def read_native_workflow(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        with native_session_confirmed(session.token) as current:
            task = WorkflowExecutor(request.app.state.memory_store).detail(current.principal, fields["task_id"], _now())
        return _success(task_json=json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (ValueError, UnicodeError):
        return _error("session_required")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("session_required")
    except WorkflowError as exc:
        return _workflow_error(exc)


@router.post("/v1/app/workflows/approve")
async def approve_native_workflow(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        if fields["confirm"] != "approve-workflow-local":
            return _error("scope_invalid")
        with native_review_grant_confirmed(session.token) as (current, grant):
            approved = WorkflowExecutor(request.app.state.memory_store).approve(
                current.principal, fields["task_id"], fields["expected_sha256"],
                session_binding(current.token), grant.id, _now(),
            )
        return _success(arguments_sha=approved["arguments_sha"], expires_at=approved["expires_at"])
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("grant_required")
    except WorkflowError as exc:
        return _workflow_error(exc)


@router.post("/v1/app/workflows/execute")
async def execute_native_workflow(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        executor = WorkflowExecutor(request.app.state.memory_store)
        with native_session_confirmed(session.token) as current:
            detail = executor.detail(current.principal, fields["task_id"], _now())
        if detail["tool_id"] == "simulate_action":
            grant_id = executor.approval_grant_id(session.principal, fields["task_id"], _now())
            with native_review_grant_confirmed(session.token, grant_id) as (current, grant):
                result = executor.execute(
                    current.principal, fields["task_id"], fields["idempotency_key"],
                    session_binding(current.token), grant.id, _now(),
                )
        else:
            with native_session_confirmed(session.token) as current:
                result = executor.execute(
                    current.principal, fields["task_id"], fields["idempotency_key"],
                    session_binding(current.token), None, _now(),
                )
        return _success(task_json=json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("grant_required")
    except WorkflowError as exc:
        return _workflow_error(exc)


async def _change_native_workflow(request: Request, action: str) -> PlainTextResponse:
    try:
        path = request.url.path
        fields = await _read_fields(request, EXPECTED_FIELDS[path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        with native_session_confirmed(session.token) as current:
            executor = WorkflowExecutor(request.app.state.memory_store)
            if action == "pause":
                task = executor.pause(current.principal, fields["task_id"], _now())
            elif action == "resume":
                task = executor.resume(current.principal, fields["task_id"], _now())
            else:
                task = executor.cancel(current.principal, fields["task_id"], _now())
        return _success(task_json=json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("session_required")
    except WorkflowError as exc:
        return _workflow_error(exc)


@router.post("/v1/app/workflows/pause")
async def pause_native_workflow(request: Request) -> PlainTextResponse:
    return await _change_native_workflow(request, "pause")


@router.post("/v1/app/workflows/resume")
async def resume_native_workflow(request: Request) -> PlainTextResponse:
    return await _change_native_workflow(request, "resume")


@router.post("/v1/app/workflows/cancel")
async def cancel_native_workflow(request: Request) -> PlainTextResponse:
    return await _change_native_workflow(request, "cancel")


def _encode_automation_rows(items: list[dict]) -> str:
    fields = (
        "id", "kind", "recurrence", "local_schedule", "timezone", "state",
        "next_run_at_utc", "workflow_version", "quiet_start", "quiet_end", "title",
    )
    lines = []
    for item in items:
        values = ["" if item.get(name) is None else str(item.get(name, "")) for name in fields]
        if any(any(character in value for character in "\t\n\r") for value in values):
            raise ValueError("automação inválida")
        lines.append("\t".join(values))
    return "\n".join(lines)

def _encode_automation_history(items: list[dict]) -> str:
    lines = []
    for item in items:
        sources = ",".join(str(source.get("source", "")) for source in item.get("sources", []))
        values = (
            item["id"], item["scheduled_for_utc"], item["status"], str(item["attempts"]),
            item.get("error_code") or "", item.get("completed_at") or "",
            item["workflow_version"], sources,
        )
        if any(any(character in value for character in "\t\n\r") for value in values):
            raise ValueError("histórico inválido")
        lines.append("\t".join(values))
    return "\n".join(lines)

def _encode_automation_sources(items: list[dict]) -> str:
    lines = []
    for item in items:
        values = (str(item.get("source", "")), str(item.get("id", "")), str(item.get("observed_at", "")))
        if any(any(character in value for character in ",;\t\n\r") for value in values):
            raise ValueError("proveniência inválida")
        lines.append(",".join(values))
    return ";".join(lines)

def _automation_error(exc: AutomationError) -> PlainTextResponse:
    if exc.code in {"automation_invalid", "automation_not_found", "automation_limit", "automation_conflict", "authorization_required"}:
        return _error(exc.code)
    return _error("scope_invalid" if exc.code == "scope_invalid" else "operation_failed")

def _confirm_automation_source_access(session, automation: dict) -> None:
    if automation["kind"] != "reminder":
        with mission_read_confirmed(session.principal, NATIVE_DOMAIN, session.token):
            pass

@router.post("/v1/app/automations/list")
async def list_native_automations(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        items = list_automations(request.app.state.memory_store, session.principal)
        return _success(items=_encode_automation_rows(items), count=len(items))
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except AutomationError as exc:
        return _automation_error(exc)

@router.post("/v1/app/automations/detail")
async def detail_native_automation(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        item = get_automation(request.app.state.memory_store, session.principal, fields["automation_id"])
        return _success(
            id=item["id"], kind=item["kind"], title=item["title"], recurrence=item["recurrence"],
            local_schedule=item["local_schedule"], timezone=item["timezone"], state=item["state"],
            next_run_at=item["next_run_at_utc"] or "", workflow_version=item["workflow_version"],
            sources=",".join(item["sources"]), quiet_start=item["quiet_start"] or "",
            quiet_end=item["quiet_end"] or "", message=item["message"],
        )
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except AutomationError as exc:
        return _automation_error(exc)

@router.post("/v1/app/automations/history")
async def history_native_automation(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        automation = get_automation(
            request.app.state.memory_store, session.principal, fields["automation_id"]
        )
        _confirm_automation_source_access(session, automation)
        rows = list_runs(request.app.state.memory_store, session.principal, fields["automation_id"], 5)
        return _success(items=_encode_automation_history(rows), count=len(rows))
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("authorization_required")
    except AutomationError as exc:
        return _automation_error(exc)

@router.post("/v1/app/automations/run")
async def detail_native_automation_run(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"])
        automation = get_automation(
            request.app.state.memory_store, session.principal, fields["automation_id"]
        )
        _confirm_automation_source_access(session, automation)
        item = get_run(
            request.app.state.memory_store, session.principal,
            fields["automation_id"], fields["run_id"],
        )
        output = item["result_text"][:80]
        sources = _encode_automation_sources(item["sources"])
        return _success(
            id=item["id"], status=item["status"], output=output,
            sources=sources, error_code=item["error_code"] or "",
            scheduled_for=item["scheduled_for_utc"], workflow_version=item["workflow_version"],
        )
    except (ValueError, UnicodeError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("authorization_required")
    except AutomationError as exc:
        return _automation_error(exc)

@router.post("/v1/app/automations/create")
async def create_native_automation(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        if fields["kind"] == "reminder":
            if fields["sources_confirmed"] != "none":
                return _error("scope_invalid")
        else:
            if fields["sources_confirmed"] != "local-only":
                return _error("scope_invalid")
            with mission_read_confirmed(session.principal, NATIVE_DOMAIN, session.token):
                pass
        item = create_automation(
            request.app.state.memory_store,
            owner=session.principal,
            kind=fields["kind"],
            title=fields["title"],
            recurrence=fields["recurrence"],
            local_schedule=fields["local_schedule"],
            timezone_name=fields["timezone"],
            quiet_start=fields["quiet_start"] or None,
            quiet_end=fields["quiet_end"] or None,
            message=fields["message"],
            now=_now(),
        )
        return _success(id=item["id"], state=item["state"], next_run_at=item["next_run_at_utc"], workflow_version=item["workflow_version"])
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("authorization_required")
    except AutomationError as exc:
        return _automation_error(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")

@router.post("/v1/app/automations/timezone")
async def change_native_automation_timezone(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        item = update_timezone(
            request.app.state.memory_store, session.principal, fields["automation_id"],
            fields["timezone"], _now(),
        )
        return _success(id=item["id"], timezone=item["timezone"], next_run_at=item["next_run_at_utc"] or "")
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except AutomationError as exc:
        return _automation_error(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")

@router.post("/v1/app/automations/control")
async def control_native_automation(request: Request) -> PlainTextResponse:
    try:
        fields = await _read_fields(request, EXPECTED_FIELDS[request.url.path])
        session = _native_session(fields["session_token"], fields["csrf_token"], mutation=True)
        item = get_automation(request.app.state.memory_store, session.principal, fields["automation_id"])
        if fields["action"] in {"recover", "retry"} and item["kind"] != "reminder":
            with mission_read_confirmed(session.principal, NATIVE_DOMAIN, session.token):
                pass
        updated = control_automation(
            request.app.state.memory_store,
            owner=session.principal,
            automation_id=fields["automation_id"],
            action=fields["action"],
            run_id=fields["run_id"] or None,
            now=_now(),
        )
        if fields["action"] in {"recover", "retry"}:
            scheduler = getattr(request.app.state, "local_automation_scheduler", None)
            if scheduler is not None:
                scheduler.run_due()
        return _success(id=updated["id"], state=updated["state"], next_run_at=updated["next_run_at_utc"] or "")
    except (ValueError, UnicodeError, ValidationError):
        return _error("scope_invalid")
    except HTTPException as exc:
        return _error_for(exc)
    except PermissionError:
        return _error("authorization_required")
    except AutomationError as exc:
        return _automation_error(exc)
    except (MemoryStoreError, OSError, sqlite3.Error):
        return _error("operation_failed")
