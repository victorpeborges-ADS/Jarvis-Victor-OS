"""Sessão local e concessões. Não há banco, OAuth nem dado de fixture."""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from loopback import ALLOWED_CLIENT_HOSTS, ALLOWED_ORIGINS

SESSION_COOKIE = "jarvis_session"
CSRF_HEADER = "x-csrf-token"
SESSION_TTL = timedelta(hours=12)
MAX_LOGIN_FAILURES = 8

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
    permission: str
    domain_ids: frozenset[str]
    revoked: bool = False


@dataclass
class ClassifiedRecord:
    id: str
    domain_id: str
    title: str


# Catálogo sintético do modo real. Não é lido de fixtures/demo.json.
SYNTHETIC_RECORDS: tuple[ClassifiedRecord, ...] = (
    ClassifiedRecord("synth_saude_1", "dom_saude", "ensaio local de rotina"),
    ClassifiedRecord("synth_medsyn_1", "dom_medsyn", "ensaio cujo título cita CRIVO"),
    ClassifiedRecord("synth_crivo_1", "dom_crivo", "ensaio CRIVO cujo título cita MedSyn"),
)

_sessions: dict[str, Session] = {}
_grants: dict[str, Grant] = {}
_login_failures = 0


def reset_state() -> None:
    global _login_failures
    _sessions.clear()
    _grants.clear()
    _login_failures = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expected_passphrase() -> str | None:
    value = os.environ.get("JARVIS_LOCAL_PASSPHRASE")
    if value is None or len(value) < 12:
        return None
    return value


class LoginIn(BaseModel):
    passphrase: str = Field(min_length=12, max_length=200)


class GrantIn(BaseModel):
    connector: str = Field(min_length=1, max_length=80)
    permission: str = Field(pattern="^read$")
    domain_ids: list[str] = Field(min_length=1, max_length=8)


class RealEventOut(BaseModel):
    id: str
    domain_id: str
    title: str
    dataset: str = "real"


class RealBriefingOut(BaseModel):
    dataset: str = "real"
    items: list[RealEventOut]


def _client_host(request: Request) -> str:
    if request.client is None:
        return ""
    return request.client.host or ""


def _session_from(request: Request) -> Session:
    host = _client_host(request)
    if host not in ALLOWED_CLIENT_HOSTS:
        raise HTTPException(status_code=403, detail="origem de rede recusada")
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="origem recusada")
    token = request.cookies.get(SESSION_COOKIE)
    session = _sessions.get(token or "")
    if session is None or session.expires_at <= _now():
        if token:
            _sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="sessão ausente")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.headers.get(CSRF_HEADER)
        if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
            raise HTTPException(status_code=403, detail="csrf recusado")
    return session


def _active_domains(principal: str) -> set[str]:
    allowed: set[str] = set()
    for grant in _grants.values():
        if grant.principal == principal and grant.permission == "read" and not grant.revoked:
            allowed.update(grant.domain_ids)
    return allowed


def _authorized_records(principal: str, requested_domain: str | None) -> list[ClassifiedRecord]:
    allowed = _active_domains(principal)
    if not allowed:
        raise HTTPException(status_code=403, detail="concessão ausente")
    if requested_domain is not None and requested_domain not in allowed:
        raise HTTPException(status_code=403, detail="concessão ausente")
    return [record for record in SYNTHETIC_RECORDS if record.domain_id in allowed and (requested_domain is None or record.domain_id == requested_domain)]


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


@router.post("/session", status_code=201)
def open_session(body: LoginIn, request: Request, response: Response) -> dict:
    global _login_failures
    if _client_host(request) not in ALLOWED_CLIENT_HOSTS:
        raise HTTPException(status_code=403, detail="origem de rede recusada")
    expected = _expected_passphrase()
    if expected is None:
        raise HTTPException(status_code=503, detail="sessão local não configurada")
    if _login_failures >= MAX_LOGIN_FAILURES:
        raise HTTPException(status_code=429, detail="muitas tentativas")
    if not hmac.compare_digest(body.passphrase, expected):
        _login_failures += 1
        raise HTTPException(status_code=401, detail="credencial recusada")
    _login_failures = 0
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    _sessions[token] = Session(
        token=token,
        csrf_token=csrf_token,
        principal="owner",
        expires_at=_now() + SESSION_TTL,
    )
    _set_cookie(response, token, request.url.scheme == "https")
    return {"csrf_token": csrf_token, "dataset": "real"}


@router.delete("/session", status_code=204)
def close_session(request: Request, response: Response) -> None:
    session = _session_from(request)
    _sessions.pop(session.token, None)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/grants", status_code=201)
def create_grant(body: GrantIn, request: Request) -> dict:
    session = _session_from(request)
    grant = Grant(
        id=secrets.token_hex(8),
        principal=session.principal,
        connector=body.connector,
        permission=body.permission,
        domain_ids=frozenset(body.domain_ids),
    )
    _grants[grant.id] = grant
    return {
        "id": grant.id,
        "principal": grant.principal,
        "connector": grant.connector,
        "permission": grant.permission,
        "domain_ids": sorted(grant.domain_ids),
        "revoked": grant.revoked,
    }


@router.post("/grants/{grant_id}/revoke", status_code=200)
def revoke_grant(grant_id: str, request: Request) -> dict:
    session = _session_from(request)
    grant = _grants.get(grant_id)
    if grant is None or grant.principal != session.principal:
        raise HTTPException(status_code=404, detail="concessão ausente")
    grant.revoked = True
    return {"id": grant.id, "revoked": True}


@router.get("/events", response_model=list[RealEventOut])
def read_events(request: Request, domain_id: str | None = None) -> list[RealEventOut]:
    session = _session_from(request)
    records = _authorized_records(session.principal, domain_id)
    return [RealEventOut(id=record.id, domain_id=record.domain_id, title=record.title) for record in records]


@router.get("/briefing", response_model=RealBriefingOut)
def read_briefing(request: Request) -> RealBriefingOut:
    session = _session_from(request)
    records = _authorized_records(session.principal, None)
    return RealBriefingOut(items=[RealEventOut(id=record.id, domain_id=record.domain_id, title=record.title) for record in records])


def put_grant_for_tests(grant: Grant) -> None:
    _grants[grant.id] = grant
