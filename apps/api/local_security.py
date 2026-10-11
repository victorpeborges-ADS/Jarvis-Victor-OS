"""Sessão, CSRF e autorização para o catálogo exclusivamente sintético."""

from __future__ import annotations

import hmac
import os
import secrets
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain_registry import (
    CALENDAR_INVENTORY_RESOURCE,
    CALENDAR_READ_RESOURCE,
    CANONICAL_CONNECTORS,
    CANONICAL_DOMAIN_IDS,
    CANONICAL_RESOURCES,
    MISSION_READ_RESOURCE,
    MISSION_WRITE_RESOURCE,
    MISSION_REVIEW_RESOURCE,
)
from memory_models import ProvenanceRecord, ReadScope
from memory_store import SQLiteMemoryStore, StoredEvent
from loopback import ALLOWED_ORIGINS, is_loopback_address, require_allowed_origin

SESSION_COOKIE = "jarvis_session"
CSRF_HEADER = "x-csrf-token"
SESSION_TTL = timedelta(hours=12)
MAX_LOGIN_FAILURES = 8
LOGIN_WINDOW = timedelta(minutes=10)
LOGIN_COOLDOWN = timedelta(seconds=60)
MAX_GRANT_TTL = timedelta(days=30)

router = APIRouter(prefix="/real", tags=["real"])


@dataclass
class Session:
    token: str
    csrf_token: str
    principal: str
    expires_at: datetime


@dataclass
class Grant:
    id: str
    principal: str
    connector: str
    resource_ids: frozenset[str]
    domain_ids: frozenset[str]
    expires_at: datetime
    revoked: bool = False
    session_token: str | None = None


_sessions: dict[str, Session] = {}
_grants: dict[str, Grant] = {}
_grant_lock = RLock()
_login_failures: dict[str, deque[datetime]] = defaultdict(deque)
_login_blocked_until: dict[str, datetime] = {}


def reset_state() -> None:
    """Limpa estado volátil; usado também para modelar reinício do processo."""
    with _grant_lock:
        _sessions.clear()
        _grants.clear()
    _login_failures.clear()
    _login_blocked_until.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expected_passphrase() -> str | None:
    value = os.environ.get("JARVIS_LOCAL_PASSPHRASE")
    if value is None or len(value) < 12:
        return None
    return value


def _passphrase_matches(supplied: str, expected: str) -> bool:
    try:
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
    except UnicodeEncodeError:
        return False


def _open_session_for_passphrase(passphrase: str, rate_limit_key: str) -> Session:
    """Shared G5 login operation; the ingress keeps its own origin policy."""
    expected = _expected_passphrase()
    if expected is None:
        raise HTTPException(status_code=503, detail="sessão local não configurada")
    _check_login_rate_limit(rate_limit_key)
    if not _passphrase_matches(passphrase, expected):
        _record_login_failure(rate_limit_key)
        raise HTTPException(status_code=401, detail="credencial recusada")
    _login_failures.pop(rate_limit_key, None)
    _login_blocked_until.pop(rate_limit_key, None)
    session = Session(
        token=secrets.token_urlsafe(32),
        csrf_token=secrets.token_urlsafe(32),
        principal="owner",
        expires_at=_now() + SESSION_TTL,
    )
    with _grant_lock:
        _sessions[session.token] = session
    return session


def _session_by_token(token: str) -> Session:
    with _grant_lock:
        session = _sessions.get(token)
        if session is None or session.expires_at <= _now():
            if session is not None:
                _invalidate_session_locked(token)
            raise HTTPException(status_code=401, detail="sessão ausente")
        return session


def _native_session(token: str, csrf_token: str | None = None, *, mutation: bool = False) -> Session:
    session = _session_by_token(token)
    if mutation and (not csrf_token or not hmac.compare_digest(csrf_token, session.csrf_token)):
        raise HTTPException(status_code=403, detail="csrf recusado")
    return session


def _create_grant_for_session(session: Session, body: GrantIn, *, replay_exact: bool = False) -> Grant:
    resources = frozenset(body.resource_ids)
    domains = frozenset(body.domain_ids)
    with _grant_lock:
        # The session is revalidated while the same grant lock serializes its
        # use with logout and grant mutation.
        current = _session_by_token(session.token)
        if current.principal != session.principal:
            raise HTTPException(status_code=401, detail="sessão ausente")
        exact: Grant | None = None
        for existing in _active_grants(session.principal, _now(), session.token):
            overlaps = (
                existing.connector == body.connector
                and bool(existing.resource_ids & resources)
                and bool(existing.domain_ids & domains)
            )
            identical = overlaps and existing.resource_ids == resources and existing.domain_ids == domains
            if identical and replay_exact:
                if exact is not None:
                    raise HTTPException(status_code=409, detail="grant ativo sobreposto")
                exact = existing
                continue
            if overlaps:
                raise HTTPException(status_code=409, detail="grant ativo sobreposto")
        if exact is not None:
            return exact
        grant = Grant(
            id=secrets.token_hex(16),
            principal=session.principal,
            session_token=session.token,
            connector=body.connector,
            resource_ids=resources,
            domain_ids=domains,
            expires_at=body.expires_at,
        )
        _grants[grant.id] = grant
        return grant


def _revoke_grant_for_session(
    session: Session,
    grant_id: str,
    *,
    connector: str | None = None,
    resource_id: str | None = None,
    domain_id: str | None = None,
) -> Grant:
    with _grant_lock:
        current = _session_by_token(session.token)
        if current.principal != session.principal:
            raise HTTPException(status_code=401, detail="sessão ausente")
        grant = _grants.get(grant_id)
        if grant is None or grant.principal != session.principal or grant.session_token != session.token:
            raise HTTPException(status_code=404, detail="concessão ausente")
        if (
            (connector is not None and grant.connector != connector)
            or (resource_id is not None and resource_id not in grant.resource_ids)
            or (domain_id is not None and domain_id not in grant.domain_ids)
        ):
            raise HTTPException(status_code=403, detail="escopo de concessão recusado")
        grant.revoked = True
        return grant


def _close_session_for(session: Session) -> None:
    with _grant_lock:
        current = _sessions.get(session.token)
        if current is None or current.principal != session.principal:
            raise HTTPException(status_code=401, detail="sessão ausente")
        _invalidate_session_locked(session.token)


def _invalidate_session_locked(token: str) -> None:
    """Caller holds _grant_lock: logout/expiry and grant invalidation linearize."""
    for grant in _grants.values():
        if grant.session_token == token:
            grant.revoked = True
    _sessions.pop(token, None)


class LoginIn(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    passphrase: str = Field(min_length=12, max_length=200)


class SessionOut(BaseModel):
    csrf_token: str
    dataset: Literal["real"] = "real"
    expires_at: datetime


class GrantOut(BaseModel):
    id: str
    principal: str
    connector: Literal["calendar_sim", "mission_sim"]
    permission: Literal["read"] = "read"
    resource_ids: list[str]
    domain_ids: list[str]
    expires_at: datetime
    revoked: bool = False


def _grant_response(grant: Grant) -> GrantOut:
    return GrantOut(
        id=grant.id,
        principal=grant.principal,
        connector=grant.connector,
        resource_ids=sorted(grant.resource_ids),
        domain_ids=sorted(grant.domain_ids),
        expires_at=grant.expires_at,
        revoked=grant.revoked,
    )


class GrantIn(BaseModel):
    connector: Literal["calendar_sim", "mission_sim"]
    permission: Literal["read"]
    resource_ids: list[str] = Field(min_length=1, max_length=1)
    domain_ids: list[str] = Field(min_length=1, max_length=8)
    expires_at: datetime

    @field_validator("resource_ids")
    @classmethod
    def resources_are_canonical(cls, values: list[str], info) -> list[str]:
        connector = info.data.get("connector")
        allowed = CANONICAL_RESOURCES.get(connector, frozenset())
        if any(value not in allowed for value in values) or len(set(values)) != len(values):
            raise ValueError("recurso inválido")
        return values

    @field_validator("domain_ids")
    @classmethod
    def domains_are_canonical(cls, values: list[str]) -> list[str]:
        if any(value not in CANONICAL_DOMAIN_IDS for value in values) or len(set(values)) != len(values):
            raise ValueError("domínio inválido")
        return values

    @field_validator("expires_at")
    @classmethod
    def validity_is_bounded_and_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("validade precisa de fuso horário")
        now = _now()
        utc_value = value.astimezone(timezone.utc)
        if utc_value <= now or utc_value > now + MAX_GRANT_TTL:
            raise ValueError("validade fora do intervalo permitido")
        return utc_value


class RealEventOut(BaseModel):
    id: str
    source_id: str
    connector: str
    resource_id: str
    domain_id: str
    title: str
    event_type: str
    sensitivity: str
    occurred_at: datetime | None
    end_at: datetime | None = None
    calendar_id: str | None = None
    calendar_name: str | None = None
    calendar_time_zone: str | None = None
    event_time_zone: str | None = None
    provider_updated_at: datetime | None = None
    provenance: ProvenanceRecord
    dataset: str = "real"


class RealBriefingOut(BaseModel):
    dataset: str = "real"
    items: list[RealEventOut]


def _event_response(record: StoredEvent) -> RealEventOut:
    event = record.event
    if event.domain_id is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    payload = event.payload_minimized

    def payload_datetime(key: str) -> datetime | None:
        value = payload.get(key)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None

    return RealEventOut(
        id=event.id,
        source_id=record.source.id,
        connector=record.source.provider,
        resource_id=record.source.resource_id,
        domain_id=event.domain_id,
        title=event.title,
        event_type=event.event_type,
        sensitivity=event.sensitivity,
        occurred_at=event.occurred_at,
        end_at=payload_datetime("end_at"),
        calendar_id=payload.get("calendar_id") if isinstance(payload.get("calendar_id"), str) else None,
        calendar_name=payload.get("calendar_name") if isinstance(payload.get("calendar_name"), str) else None,
        calendar_time_zone=payload.get("calendar_time_zone") if isinstance(payload.get("calendar_time_zone"), str) else None,
        event_time_zone=payload.get("event_time_zone") if isinstance(payload.get("event_time_zone"), str) else None,
        provider_updated_at=payload_datetime("provider_updated_at"),
        provenance=event.provenance,
    )


def _client_host(request: Request) -> str:
    if request.client is None:
        return ""
    return request.client.host or ""


def _session_from(request: Request, *, mutation: bool = False) -> Session:
    host = _client_host(request)
    if not is_loopback_address(host):
        raise HTTPException(status_code=403, detail="origem de rede recusada")
    origin = request.headers.get("origin")
    if mutation:
        require_allowed_origin(origin)
    elif origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="origem recusada")
    # Origin is not authentication. Loopback GET clients may omit it.
    # An explicit cross-site fetch is refused even when Origin is absent.
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site.lower() == "cross-site":
        raise HTTPException(status_code=403, detail="origem recusada")
    token = request.cookies.get(SESSION_COOKIE)
    session = _session_by_token(token or "")
    if mutation:
        supplied = request.headers.get(CSRF_HEADER)
        if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
            raise HTTPException(status_code=403, detail="csrf recusado")
    return session


def _active_grants(principal: str, at: datetime | None = None, session_token: str | None = None) -> list[Grant]:
    instant = at or _now()
    with _grant_lock:
        for token, session in list(_sessions.items()):
            if session.expires_at <= instant:
                _invalidate_session_locked(token)
        return [grant for grant in _grants.values()
                if grant.principal == principal and not grant.revoked and grant.expires_at > instant
                and (session_token is None or grant.session_token == session_token)
                and (grant.session_token is None or grant.session_token in _sessions)]


def _calendar_domains_for(principal: str, resource_id: str) -> frozenset[str]:
    """Domains of active calendar grants that carry one exact canonical resource."""
    allowed: set[str] = set()
    canonical = CANONICAL_RESOURCES["calendar_sim"]
    with _grant_lock:
        for grant in _active_grants(principal):
            if grant.connector != "calendar_sim":
                continue
            if resource_id not in grant.resource_ids or not grant.resource_ids <= canonical:
                continue
            allowed.update(grant.domain_ids & CANONICAL_DOMAIN_IDS)
    return frozenset(allowed)


def authorized_calendar_domains(principal: str) -> frozenset[str]:
    """Domains covered by an active calendar event-read grant.

    The limited inventory resource does not authorize event reads or sync.
    """
    return _calendar_domains_for(principal, CALENDAR_READ_RESOURCE)


def authorized_calendar_inventory_domains(principal: str) -> frozenset[str]:
    """Domains in which unclassified calendar names may be discovered."""
    return _calendar_domains_for(principal, CALENDAR_INVENTORY_RESOURCE)


@contextmanager
def mission_read_confirmed(principal: str, domain_id: str, session_token: str | None = None):
    """Keep a synthetic mission read grant active while assembling its response."""
    with _grant_lock:
        _confirm_session_locked(principal, session_token)
        if domain_id not in mission_domains(principal, MISSION_READ_RESOURCE, session_token):
            raise PermissionError("concessão de leitura revogada ou expirada")
        yield


def _confirm_session_locked(principal: str, session_token: str | None) -> None:
    if session_token is None:
        return
    session = _sessions.get(session_token)
    if session is None or session.principal != principal or session.expires_at <= _now():
        if session is not None and session.expires_at <= _now():
            _invalidate_session_locked(session_token)
        raise PermissionError("sessão encerrada ou expirada")


@contextmanager
def mission_read_scope_confirmed(
    principal: str,
    domain_id: str | None = None,
    session_token: str | None = None,
):
    """Hold the read grant stable while a mission snapshot is selected and copied.

    Lock order is grant lock, then SQLite reads. The yielded set is the exact
    authorized scope for this response snapshot.
    """
    with _grant_lock:
        _confirm_session_locked(principal, session_token)
        granted = mission_domains(principal, MISSION_READ_RESOURCE, session_token)
        allowed = granted if domain_id is None else granted & {domain_id}
        if not allowed:
            raise PermissionError("concessão de leitura revogada ou expirada")
        yield frozenset(allowed)


@contextmanager
def mission_review_read_scope_confirmed(
    principal: str,
    domain_id: str | None = None,
    session_token: str | None = None,
):
    """Hold read/review grants stable while review snapshots are assembled."""
    with _grant_lock:
        _confirm_session_locked(principal, session_token)
        granted = mission_domains(principal, MISSION_READ_RESOURCE, session_token) | mission_domains(principal, MISSION_REVIEW_RESOURCE, session_token)
        allowed = granted if domain_id is None else granted & {domain_id}
        if not allowed:
            raise PermissionError("concessão de leitura ou revisão revogada ou expirada")
        yield frozenset(allowed)


@contextmanager
def mission_write_confirmed(principal: str, domain_id: str, session_token: str | None = None):
    """Hold grant revocation stable until the caller finishes its SQLite commit.

    Lock order is grant lock, then the SQLite write transaction. Callers must
    not acquire the grant lock while already inside a SQLite transaction:
    event reads take the grant lock first and then the database.
    """
    with _grant_lock:
        _confirm_session_locked(principal, session_token)
        if domain_id not in mission_domains(principal, MISSION_WRITE_RESOURCE, session_token):
            raise PermissionError("concessão de missão revogada ou expirada")
        yield


@contextmanager
def mission_review_confirmed(principal: str, domain_id: str, session_token: str | None = None):
    """Hold review grant revocation stable until the review decision SQLite commit.

    Lock order is grant lock, then the SQLite write transaction.
    """
    with _grant_lock:
        _confirm_session_locked(principal, session_token)
        if domain_id not in mission_domains(principal, MISSION_REVIEW_RESOURCE, session_token):
            raise PermissionError("concessão de revisão revogada ou expirada")
        yield


def mission_domains(principal: str, resource_id: str, session_token: str | None = None) -> frozenset[str]:
    """Domains covered by an active mission_sim grant for one resource.

    A calendar grant never contributes. domain_id classifies; it does not authorize.
    """
    if resource_id not in {MISSION_READ_RESOURCE, MISSION_WRITE_RESOURCE, MISSION_REVIEW_RESOURCE}:
        return frozenset()
    allowed: set[str] = set()
    canonical = CANONICAL_RESOURCES["mission_sim"]
    with _grant_lock:
        for grant in _active_grants(principal, session_token=session_token):
            if grant.connector != "mission_sim":
                continue
            if resource_id not in grant.resource_ids or not grant.resource_ids <= canonical:
                continue
            allowed.update(grant.domain_ids & CANONICAL_DOMAIN_IDS)
    return frozenset(allowed)


@contextmanager
def calendar_grant_guard(principal: str, required_domains: set[str] | frozenset[str]):
    """Hold grant mutation stable while committing a page or preparing its response.

    Revocation and page commit linearize on ``_grant_lock``. No provider/network
    operation may run inside this context.
    """
    with _grant_lock:
        if not required_domains <= authorized_calendar_domains(principal):
            raise PermissionError("concessão de Calendar revogada")
        yield


def _authorized_records(
    principal: str,
    store: SQLiteMemoryStore,
    requested_domain: str | None,
    record_id: str | None = None,
) -> list[StoredEvent]:
    # Authorization, SQLite selection, and the returned row snapshot share the
    # same linearization lock as grant revocation. A request that enters this
    # critical section first is authorized before revocation; revoke waits for
    # it. Requests entering after revocation see no active scope.
    with _grant_lock:
        return _authorized_records_locked(principal, store, requested_domain, record_id)


def _authorized_records_locked(
    principal: str,
    store: SQLiteMemoryStore,
    requested_domain: str | None,
    record_id: str | None = None,
) -> list[StoredEvent]:
    if requested_domain is not None and requested_domain not in CANONICAL_DOMAIN_IDS:
        raise HTTPException(status_code=403, detail="concessão ausente")
    grants = _active_grants(principal)
    if not grants:
        raise HTTPException(status_code=403, detail="concessão ausente")
    scopes: list[ReadScope] = []
    for grant in grants:
        if grant.connector not in CANONICAL_CONNECTORS:
            continue
        valid_domains = frozenset(grant.domain_ids & CANONICAL_DOMAIN_IDS)
        event_resources = frozenset({CALENDAR_READ_RESOURCE}) if grant.connector == "calendar_sim" else frozenset()
        valid_resources = grant.resource_ids & event_resources
        for resource_id in valid_resources:
            if valid_domains:
                scopes.append(ReadScope(
                    connector=grant.connector,
                    resource_id=resource_id,
                    domain_ids=valid_domains,
                ))
    if not scopes:
        raise HTTPException(status_code=403, detail="concessão ausente")
    if requested_domain is not None and not any(requested_domain in scope.domain_ids for scope in scopes):
        raise HTTPException(status_code=403, detail="concessão ausente")

    if record_id is None:
        found = store.list_authorized_events(scopes, requested_domain)
    else:
        record = store.get_authorized_event(record_id, scopes, requested_domain)
        found = [record] if record is not None else []
    authorized = [
        record for record in found
        if record.event.domain_id in CANONICAL_DOMAIN_IDS
        and record.source.provider in CANONICAL_CONNECTORS
        and record.source.resource_id in CANONICAL_RESOURCES.get(record.source.provider, frozenset())
        and any(
            scope.connector == record.source.provider
            and scope.resource_id == record.source.resource_id
            and record.event.domain_id in scope.domain_ids
            for scope in scopes
        )
    ]
    if record_id is not None and not authorized:
        # Resposta uniforme evita revelar se o ID existe fora do escopo concedido.
        raise HTTPException(status_code=404, detail="registro ausente")
    # A valid scope with no matching rows is an authorized empty collection.
    # Keep 403 for missing scopes above and 404 for direct IDs to avoid both
    # false authorization failures and existence leaks.
    return authorized


def _store_from(request: Request) -> SQLiteMemoryStore:
    return request.app.state.memory_store


def _set_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=int(SESSION_TTL.total_seconds()),
    )


def _rate_limit_key(request: Request) -> str:
    return _client_host(request)


def _check_login_rate_limit(key: str) -> None:
    now = _now()
    blocked_until = _login_blocked_until.get(key)
    if blocked_until and blocked_until > now:
        seconds = max(1, int((blocked_until - now).total_seconds()))
        raise HTTPException(status_code=429, detail="muitas tentativas; aguarde e tente novamente", headers={"Retry-After": str(seconds)})
    if blocked_until:
        _login_blocked_until.pop(key, None)
    failures = _login_failures[key]
    while failures and failures[0] <= now - LOGIN_WINDOW:
        failures.popleft()


def _record_login_failure(key: str) -> None:
    now = _now()
    failures = _login_failures[key]
    failures.append(now)
    if len(failures) >= MAX_LOGIN_FAILURES:
        _login_blocked_until[key] = now + LOGIN_COOLDOWN


@router.post("/session", status_code=201)
def open_session(body: LoginIn, request: Request, response: Response) -> SessionOut:
    require_allowed_origin(request.headers.get("origin"))
    key = _rate_limit_key(request)
    if not is_loopback_address(key):
        raise HTTPException(status_code=403, detail="origem de rede recusada")
    session = _open_session_for_passphrase(body.passphrase, key)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    _set_cookie(response, session.token, request.url.scheme == "https")
    return SessionOut(csrf_token=session.csrf_token, expires_at=session.expires_at)


@router.get("/session", response_model=SessionOut)
def current_session(request: Request, response: Response) -> SessionOut:
    # Browsers need to recover the session-bound CSRF value after a page reload.
    # Exact Origin validation and the HttpOnly session cookie remain mandatory.
    require_allowed_origin(request.headers.get("origin"))
    session = _session_from(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SessionOut(csrf_token=session.csrf_token, expires_at=session.expires_at)


@router.delete("/session", status_code=204)
def close_session(request: Request, response: Response) -> None:
    session = _session_from(request, mutation=True)
    _close_session_for(session)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/grants", response_model=list[GrantOut])
def list_active_grants(request: Request, response: Response) -> list[GrantOut]:
    require_allowed_origin(request.headers.get("origin"))
    session = _session_from(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    with _grant_lock:
        _session_by_token(session.token)
        active = _active_grants(session.principal, session_token=session.token)
        return [_grant_response(grant) for grant in sorted(active, key=lambda item: item.id)]


@router.post("/grants", status_code=201, response_model=GrantOut)
def create_grant(body: GrantIn, request: Request) -> GrantOut:
    session = _session_from(request, mutation=True)
    try:
        grant = _create_grant_for_session(session, body)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(status_code=409, detail="grant ativo sobreposto; revogue-o antes de conceder novamente") from exc
        raise
    return _grant_response(grant)


@router.post("/grants/{grant_id}/revoke", status_code=200)
def revoke_grant(grant_id: str, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    grant = _revoke_grant_for_session(session, grant_id)
    return {"id": grant.id, "revoked": True}


@router.get("/events", response_model=list[RealEventOut])
def read_events(request: Request, domain_id: str | None = None) -> list[RealEventOut]:
    session = _session_from(request)
    records = _authorized_records(session.principal, _store_from(request), domain_id)
    return [_event_response(record) for record in records]


@router.get("/events/{record_id}", response_model=RealEventOut)
def read_event(record_id: str, request: Request) -> RealEventOut:
    session = _session_from(request)
    record = _authorized_records(session.principal, _store_from(request), None, record_id)[0]
    return _event_response(record)


@router.get("/briefing", response_model=RealBriefingOut)
def read_briefing(request: Request) -> RealBriefingOut:
    session = _session_from(request)
    records = _authorized_records(session.principal, _store_from(request), None)
    return RealBriefingOut(items=[_event_response(record) for record in records])


def put_grant_for_tests(grant: Grant) -> None:
    with _grant_lock:
        if grant.session_token is None:
            sessions = [session for session in _sessions.values() if session.principal == grant.principal]
            if len(sessions) == 1:
                grant.session_token = sessions[0].token
        _grants[grant.id] = grant


def put_session_for_tests(token: str, principal: str, csrf_token: str) -> None:
    _sessions[token] = Session(
        token=token,
        csrf_token=csrf_token,
        principal=principal,
        expires_at=_now() + SESSION_TTL,
    )
