"""Local synthetic artifact review and human approval API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from domain_registry import CANONICAL_DOMAIN_IDS
from local_security import _session_from, mission_domains
from mission_repository import MissionConflict, MissionCorrupt, MissionDenied, MissionRejected, MissionRepository

router = APIRouter(prefix="/real/reviews", tags=["reviews-synthetic"])


class ReviewDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected", "changes_requested"]
    expected_revision: int = Field(ge=1, le=100000)
    expected_artifact_sha256: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=160)
    reason: str | None = Field(default=None, max_length=500)


class ReviewReviseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_content: str = Field(min_length=1, max_length=50000)
    idempotency_key: str = Field(min_length=8, max_length=160)


def _repo(request: Request) -> MissionRepository:
    return MissionRepository(request.app.state.memory_store)


@router.get("")
def list_reviews(
    request: Request,
    domain_id: str | None = None,
    state: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    session = _session_from(request)
    readable = (
        mission_domains(session.principal, "mission:read")
        | mission_domains(session.principal, "mission:review")
    )
    if not readable:
        raise HTTPException(status_code=403, detail="concessão de missão ausente")
    if domain_id is not None:
        if domain_id not in readable:
            raise HTTPException(status_code=403, detail="concessão de missão ausente")
        allowed = {domain_id}
    else:
        allowed = readable

    return _repo(request).list_reviews(session.principal, domain_id, state, limit, cursor, allowed)


@router.get("/{review_id}")
def read_review(review_id: str, request: Request) -> dict:
    session = _session_from(request)
    try:
        record = _repo(request).get_review(session.principal, review_id)
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de revisão") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    readable = (
        mission_domains(session.principal, "mission:read")
        | mission_domains(session.principal, "mission:review")
    )
    if record["domain_id"] not in readable:
        raise HTTPException(status_code=403, detail="concessão de missão ausente")
    return record


@router.post("/{review_id}/decide")
def decide_review(review_id: str, body: ReviewDecisionIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    try:
        current = _repo(request).get_review(session.principal, review_id)
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de revisão") from exc
    if current is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    reviewable = mission_domains(session.principal, "mission:review")
    if current["domain_id"] not in reviewable:
        raise HTTPException(status_code=403, detail="concessão de revisão ausente")

    try:
        record, replayed = _repo(request).decide_review(
            session.principal,
            review_id,
            body.decision,
            body.expected_revision,
            body.expected_artifact_sha256,
            body.reason,
            body.idempotency_key,
            session.token,
        )
        return {**record, "replayed": replayed}
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MissionDenied as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc
    except MissionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de revisão") from exc


@router.post("/{review_id}/revise")
def revise_review(review_id: str, body: ReviewReviseIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    try:
        current = _repo(request).get_review(session.principal, review_id)
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de revisão") from exc
    if current is None:
        raise HTTPException(status_code=404, detail="registro ausente")
    writable = mission_domains(session.principal, "mission:write")
    if current["domain_id"] not in writable:
        raise HTTPException(status_code=403, detail="concessão de escrita ausente")
    reviewable = mission_domains(session.principal, "mission:review")
    if current["domain_id"] not in reviewable:
        raise HTTPException(status_code=403, detail="concessão de revisão ausente")

    try:
        record, replayed = _repo(request).revise_review(
            session.principal,
            review_id,
            body.new_content,
            body.idempotency_key,
            session.token,
        )
        return {**record, "replayed": replayed}
    except MissionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MissionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except MissionDenied as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc
    except MissionCorrupt as exc:
        raise HTTPException(status_code=409, detail="integridade do registro de revisão") from exc
