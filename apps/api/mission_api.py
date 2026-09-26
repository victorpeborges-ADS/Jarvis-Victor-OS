"""Local synthetic mission API. Calendar grants do not authorize these routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from domain_registry import CANONICAL_DOMAIN_IDS
from local_security import _session_from, mission_domains
from mission_engine import available_actions
from mission_repository import MissionConflict, MissionCorrupt, MissionDenied, MissionRejected, MissionRepository

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
        record, replayed = _repo(request).create(session.principal, body.title, body.domain_id, body.idempotency_key)
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MissionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    return _public({**record, "replayed": replayed})


@router.get("")
def list_missions(request: Request, domain_id: str | None = None, limit: int = 20, cursor: str | None = None) -> dict:
    session = _session_from(request)
    if domain_id is not None:
        _require(session.principal, "mission:read", domain_id)
        allowed = {domain_id}
    else:
        allowed = mission_domains(session.principal, "mission:read")
        if not allowed:
            raise HTTPException(status_code=403, detail="concessão de missão ausente")
    page = _repo(request).list_page(session.principal, domain_id, limit, cursor, allowed)
    page["items"] = [_public(item) for item in page["items"]]
    return page


@router.get("/{mission_id}")
def read_mission(mission_id: str, request: Request) -> dict:
    session = _session_from(request)
    try:
        record = _repo(request).get(session.principal, mission_id)
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de missão") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    _require(session.principal, "mission:read", record["mission"]["domain_id"])
    return _public(record)


@router.get("/{mission_id}/reviews")
def list_mission_reviews(mission_id: str, request: Request) -> dict:
    session = _session_from(request)
    current = _repo(request).get(session.principal, mission_id)
    if current is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    _require(session.principal, "mission:read", current["mission"]["domain_id"])
    return _repo(request).list_reviews(session.principal, domain_id=current["mission"]["domain_id"])


@router.post("/{mission_id}/transition")
def transition_mission(mission_id: str, body: MissionTransitionIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    current = _repo(request).get(session.principal, mission_id)
    if current is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    _require(session.principal, "mission:write", current["mission"]["domain_id"])
    try:
        return _public(_repo(request).transition(
            session.principal, mission_id, body.action, body.expected_revision, body.idempotency_key
        ))
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MissionDenied as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc
    except MissionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc


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
        result = _repo(request).import_valid(session.principal, safe, body.idempotency_key)
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    result["quarantined"] = quarantined + result.get("quarantined", [])
    return result
