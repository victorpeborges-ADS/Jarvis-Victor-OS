"""Local synthetic mission API. Calendar grants do not authorize these routes."""

from __future__ import annotations

from contextlib import ExitStack

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from domain_registry import CANONICAL_DOMAIN_IDS
from local_security import _session_from, mission_domains, mission_read_scope_confirmed, mission_write_confirmed
from mission_engine import available_actions
from mission_repository import MissionConflict, MissionCorrupt, MissionDenied, MissionRejected, MissionRepository
from source_admission import redact_mission_record

router = APIRouter(prefix="/real/missions", tags=["missions-synthetic"])


class MissionCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=240)
    domain_id: str
    idempotency_key: str = Field(min_length=8, max_length=160)


class MissionTransitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern=r"^(run_next|resume|fail|retry|cancel)$")
    expected_revision: int = Field(ge=1, le=100000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MissionImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    missions: list[dict] = Field(max_length=20)
    idempotency_key: str = Field(min_length=8, max_length=160)
    confirm: bool = False


def _public(record: dict) -> dict:
    if "mission" in record:
        record = dict(record)
        record["available_actions"] = available_actions(record["mission"]["status"])
    return record


def _safe_public(request: Request, record: dict) -> dict:
    with request.app.state.memory_store.transaction() as connection:
        safe = redact_mission_record(connection, record)
    return _public(safe)


def _repo(request: Request) -> MissionRepository:
    return MissionRepository(request.app.state.memory_store)


def _require(principal: str, resource: str, domain_id: str) -> None:
    if domain_id not in mission_domains(principal, resource):
        raise HTTPException(status_code=403, detail="concessão de missão ausente")


@router.post("", status_code=201)
def create_mission(body: MissionCreateIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    if body.domain_id not in CANONICAL_DOMAIN_IDS:
        raise HTTPException(status_code=422, detail="domínio desconhecido")
    _require(session.principal, "mission:write", body.domain_id)
    try:
        with mission_write_confirmed(session.principal, body.domain_id, session.token):
            record, replayed = _repo(request).create(session.principal, body.title, body.domain_id, body.idempotency_key)
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MissionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada ou expirada") from exc
    return _safe_public(request, {**record, "replayed": replayed})


@router.get("")
def list_missions(request: Request, domain_id: str | None = None, limit: int = 20, cursor: str | None = None) -> dict:
    session = _session_from(request)
    try:
        with mission_read_scope_confirmed(session.principal, domain_id, session.token) as allowed:
            page = _repo(request).list_page(session.principal, domain_id, limit, cursor, allowed)
            page["items"] = [_safe_public(request, item) for item in page["items"]]
            return page
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão de leitura ou sessão revogada ou expirada") from exc


@router.get("/{mission_id}")
def read_mission(mission_id: str, request: Request) -> dict:
    session = _session_from(request)
    try:
        with mission_read_scope_confirmed(session.principal, session_token=session.token) as allowed:
            record = _repo(request).get(session.principal, mission_id)
            if record is None:
                raise HTTPException(status_code=404, detail="registro ausente")
            if record["mission"]["domain_id"] not in allowed:
                raise HTTPException(status_code=403, detail="concessão de leitura ausente para este domínio")
            return _safe_public(request, record)
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de missão") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão de leitura ou sessão revogada ou expirada") from exc


@router.get("/{mission_id}/reviews")
def list_mission_reviews(mission_id: str, request: Request) -> dict:
    session = _session_from(request)
    try:
        with mission_read_scope_confirmed(session.principal, session_token=session.token) as allowed:
            current = _repo(request).get(session.principal, mission_id)
            if current is None:
                raise HTTPException(status_code=404, detail="registro ausente")
            domain_id = current["mission"]["domain_id"]
            if domain_id not in allowed:
                raise HTTPException(status_code=403, detail="concessão de leitura ausente para este domínio")
            return _repo(request).list_reviews(session.principal, domain_id=domain_id)
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de missão") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão de leitura ou sessão revogada ou expirada") from exc


@router.post("/{mission_id}/transition")
def transition_mission(mission_id: str, body: MissionTransitionIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    current = _repo(request).get(session.principal, mission_id)
    if current is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    _require(session.principal, "mission:write", current["mission"]["domain_id"])
    try:
        if body.action in {"run_next", "resume"}:
            updated = _repo(request).transition(
                session.principal, mission_id, body.action, body.expected_revision,
                body.idempotency_key, session.token,
            )
        else:
            with mission_write_confirmed(session.principal, current["mission"]["domain_id"], session.token):
                updated = _repo(request).transition(
                    session.principal, mission_id, body.action, body.expected_revision,
                    body.idempotency_key, session.token,
                )
        return _safe_public(request, updated)
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MissionDenied as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc
    except MissionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada ou expirada") from exc


@router.post("/import")
def import_missions(body: MissionImportIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    if not body.confirm:
        raise HTTPException(status_code=422, detail="importação exige confirmação explícita")
    writable = mission_domains(session.principal, "mission:write")
    if not writable:
        raise HTTPException(status_code=403, detail="concessão de missão ausente")
    safe = []
    quarantined = []
    for index, document in enumerate(body.missions):
        domain_id = document.get("domain_id") if isinstance(document, dict) else None
        if domain_id not in writable:
            quarantined.append({"index": index, "reason": "domínio fora da concessão"})
            continue
        safe.append(document)
    try:
        with ExitStack() as grants:
            for domain in sorted({document["domain_id"] for document in safe}):
                grants.enter_context(mission_write_confirmed(session.principal, domain, session.token))
            result = _repo(request).import_valid(session.principal, safe, body.idempotency_key)
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MissionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada ou expirada") from exc
    result["quarantined"] = quarantined + result.get("quarantined", [])
    return result
