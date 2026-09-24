"""Sessão, CSRF e autorização para o catálogo exclusivamente sintético."""

from __future__ import annotations

import hmac
import os
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain_registry import CANONICAL_CONNECTORS, CANONICAL_DOMAIN_IDS, CANONICAL_RESOURCES
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


_sessions: dict[str, Session] = {}
_grants: dict[str, Grant] = {}
_login_failures: dict[str, deque[datetime]] = defaultdict(deque)
_login_blocked_until: dict[str, datetime] = {}


def reset_state() -> None:
    """Limpa estado volátil; usado também para modelar reinício do processo."""
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


class LoginIn(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    passphrase: str = Field(min_length=12, max_length=200)


class GrantIn(BaseModel):
    connector: Literal["calendar_sim"]
    permission: Literal["read"]
    resource_ids: list[str] = Field(min_length=1, max_length=1)
    domain_ids: list[str] = Field(min_length=1, max_length=8)
    expires_at: datetime

    @field_validator("resource_ids")
    @classmethod
    def resources_are_canonical(cls, values: list[str]) -> list[str]:
        allowed = CANONICAL_RESOURCES["calendar_sim"]
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
    connector: str
    resource_id: str
    domain_id: str
    title: str
    event_type: str
    sensitivity: str
    occurred_at: datetime | None
    provenance: ProvenanceRecord
    dataset: str = "real"


class RealBriefingOut(BaseModel):
    dataset: str = "real"
    items: list[RealEventOut]


def _event_response(record: StoredEvent) -> RealEventOut:
    event = record.event
    if event.domain_id is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    return RealEventOut(
        id=event.id,
        connector=record.source.provider,
        resource_id=record.source.resource_id,
        domain_id=event.domain_id,
        title=event.title,
        event_type=event.event_type,
        sensitivity=event.sensitivity,
        occurred_at=event.occurred_at,
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
    token = request.cookies.get(SESSION_COOKIE)
    session = _sessions.get(token or "")
    if session is None or session.expires_at <= _now():
        if token:
            _sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="sessão ausente")
    if mutation:
        supplied = request.headers.get(CSRF_HEADER)
        if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
            raise HTTPException(status_code=403, detail="csrf recusado")
    return session


def _active_grants(principal: str, at: datetime | None = None) -> list[Grant]:
    instant = at or _now()
    return [grant for grant in _grants.values() if grant.principal == principal and not grant.revoked and grant.expires_at > instant]


def _authorized_records(
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
        valid_resources = grant.resource_ids & CANONICAL_RESOURCES.get(grant.connector, frozenset())
        for resource_id in valid_resources:
            if valid_domains:
                scopes.append(ReadScope(
                    connector=grant.connector,
                    resource_id=resource_id,
                    domain_ids=valid_domains,
                ))
    if not scopes:
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
    if not authorized:
        raise HTTPException(status_code=403, detail="concessão ausente")
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
def open_session(body: LoginIn, request: Request, response: Response) -> dict:
    require_allowed_origin(request.headers.get("origin"))
    key = _rate_limit_key(request)
    if not is_loopback_address(key):
        raise HTTPException(status_code=403, detail="origem de rede recusada")
    expected = _expected_passphrase()
    if expected is None:
        raise HTTPException(status_code=503, detail="sessão local não configurada")
    _check_login_rate_limit(key)
    if not hmac.compare_digest(body.passphrase, expected):
        _record_login_failure(key)
        raise HTTPException(status_code=401, detail="credencial recusada")
    _login_failures.pop(key, None)
    _login_blocked_until.pop(key, None)
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    _sessions[token] = Session(
        token=token,
        csrf_token=csrf_token,
        principal="owner",
        expires_at=_now() + SESSION_TTL,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    _set_cookie(response, token, request.url.scheme == "https")
    return {"csrf_token": csrf_token, "dataset": "real"}


@router.delete("/session", status_code=204)
def close_session(request: Request, response: Response) -> None:
    session = _session_from(request, mutation=True)
    _sessions.pop(session.token, None)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/grants", status_code=201)
def create_grant(body: GrantIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    resources = frozenset(body.resource_ids)
    domains = frozenset(body.domain_ids)
    now = _now()
    for existing in _active_grants(session.principal, now):
        overlaps = (
            existing.connector == body.connector
            and bool(existing.resource_ids & resources)
            and bool(existing.domain_ids & domains)
        )
        if overlaps:
            raise HTTPException(status_code=409, detail="grant ativo sobreposto; revogue-o antes de conceder novamente")
    grant = Grant(
        id=secrets.token_hex(16),
        principal=session.principal,
        connector=body.connector,
        resource_ids=resources,
        domain_ids=domains,
        expires_at=body.expires_at,
    )
    _grants[grant.id] = grant
    return {
        "id": grant.id,
        "principal": grant.principal,
        "connector": grant.connector,
        "permission": "read",
        "resource_ids": sorted(grant.resource_ids),
        "domain_ids": sorted(grant.domain_ids),
        "expires_at": grant.expires_at.isoformat(),
        "revoked": grant.revoked,
    }


@router.post("/grants/{grant_id}/revoke", status_code=200)
def revoke_grant(grant_id: str, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    grant = _grants.get(grant_id)
    if grant is None or grant.principal != session.principal:
        raise HTTPException(status_code=404, detail="concessão ausente")
    grant.revoked = True
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
    _grants[grant.id] = grant
