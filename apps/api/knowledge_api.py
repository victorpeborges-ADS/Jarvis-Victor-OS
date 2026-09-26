"""Explicit review of synthetic derived knowledge and bounded context assembly."""

from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import ExitStack
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from local_security import (
    _session_from, mission_domains, mission_read_confirmed, mission_review_confirmed,
)
from mission_repository import _now, _sha

router = APIRouter(prefix="/real/knowledge", tags=["knowledge-synthetic"])


class KnowledgeDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    expected_content_sha256: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=160)
    reason: str | None = Field(default=None, max_length=500)


def _content_sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _source_review(connection, row):
    if row["source_review_id"]:
        return connection.execute(
            "SELECT * FROM mission_artifact_reviews WHERE id=? AND mission_id=? AND owner=?",
            (row["source_review_id"], row["mission_id"], row["owner"]),
        ).fetchone()
    if not row["id"].startswith("knowledge_capture_"):
        return None
    artifact_id = "artifact_capture_" + row["id"].removeprefix("knowledge_capture_")
    return connection.execute(
        """SELECT * FROM mission_artifact_reviews
           WHERE mission_id=? AND owner=? AND artifact_id=?
           ORDER BY artifact_version DESC LIMIT 1""",
        (row["mission_id"], row["owner"], artifact_id),
    ).fetchone()


def _valid_source(row) -> bool:
    if row is None or row["state"] != "approved":
        return False
    try:
        snapshot = json.loads(row["artifact_snapshot_json"])
        return _sha(snapshot) == row["artifact_sha256"] and snapshot.get("id") == row["artifact_id"]
    except (TypeError, ValueError, AttributeError):
        return False


@router.get("")
def list_knowledge(request: Request, domain_id: str | None = None) -> dict:
    session = _session_from(request)
    allowed = mission_domains(session.principal, "mission:read")
    if not allowed or (domain_id is not None and domain_id not in allowed):
        raise HTTPException(status_code=403, detail="concessão de leitura ausente")
    domains = sorted({domain_id} if domain_id else allowed)
    placeholders = ",".join("?" for _ in domains)
    try:
        with ExitStack() as grants:
            for domain in domains:
                grants.enter_context(mission_read_confirmed(session.principal, domain, session.token))
            with request.app.state.memory_store.transaction() as connection:
                rows = connection.execute(
                    f"""SELECT k.id, k.mission_id, k.domain_id, k.content, k.skill_version,
                           k.kind,
                           k.created_at, d.decision, d.decided_at, d.source_review_id
                    FROM mission_knowledge k LEFT JOIN mission_knowledge_decisions d
                      ON d.knowledge_id=k.id AND d.owner=k.owner
                    WHERE k.owner=? AND k.domain_id IN ({placeholders})
                    ORDER BY k.created_at DESC, k.id LIMIT 100""",
                    (session.principal, *domains),
                ).fetchall()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão de leitura revogada ou expirada") from exc
    return {"dataset": "api_synthetic", "items": [
        {**dict(row), "state": row["decision"] or "staged",
         "content_sha256": _content_sha(row["content"])} for row in rows
    ]}


@router.post("/{knowledge_id}/decide")
def decide_knowledge(knowledge_id: str, body: KnowledgeDecisionIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    clean_reason = body.reason.strip() if body.reason else None
    if body.decision == "rejected" and not clean_reason:
        raise HTTPException(status_code=422, detail="motivo obrigatório para rejeição")
    store = request.app.state.memory_store
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM mission_knowledge WHERE id=? AND owner=?",
            (knowledge_id, session.principal),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="conhecimento ausente")
    try:
        with mission_review_confirmed(session.principal, row["domain_id"], session.token):
            with store.transaction() as connection:
                fresh = connection.execute(
                    "SELECT * FROM mission_knowledge WHERE id=? AND owner=?",
                    (knowledge_id, session.principal),
                ).fetchone()
                if fresh is None or fresh["domain_id"] != row["domain_id"]:
                    raise HTTPException(status_code=409, detail="conhecimento alterado")
                actual_sha = _content_sha(fresh["content"])
                if actual_sha != body.expected_content_sha256:
                    raise HTTPException(status_code=409, detail="conteúdo do conhecimento divergente")
                prior_key = connection.execute(
                    "SELECT * FROM mission_knowledge_decisions WHERE owner=? AND idempotency_key=?",
                    (session.principal, body.idempotency_key),
                ).fetchone()
                if prior_key is not None:
                    if (prior_key["knowledge_id"] != knowledge_id or prior_key["decision"] != body.decision
                            or prior_key["knowledge_sha256"] != actual_sha or prior_key["reason"] != clean_reason):
                        raise HTTPException(status_code=409, detail="idempotência reutilizada com corpo diferente")
                    return {"dataset": "api_synthetic", "id": knowledge_id,
                            "state": prior_key["decision"], "replayed": True,
                            "source_review_id": prior_key["source_review_id"]}
                if connection.execute(
                    "SELECT id FROM mission_knowledge_decisions WHERE knowledge_id=?", (knowledge_id,),
                ).fetchone() is not None:
                    raise HTTPException(status_code=409, detail="conhecimento já decidido")
                source = _source_review(connection, fresh)
                if body.decision == "approved" and not _valid_source(source):
                    raise HTTPException(status_code=409, detail="artefato de origem ainda não aprovado ou desatualizado")
                source_id = source["id"] if source is not None else None
                source_sha = source["artifact_sha256"] if source is not None else None
                connection.execute(
                    """INSERT INTO mission_knowledge_decisions
                       (id, knowledge_id, mission_id, owner, domain_id, decision,
                        knowledge_sha256, source_review_id, source_artifact_sha256,
                        actor, reason, idempotency_key, decided_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f"kdec_{secrets.token_hex(8)}", knowledge_id, fresh["mission_id"],
                     session.principal, fresh["domain_id"], body.decision, actual_sha,
                     source_id, source_sha, session.principal, clean_reason,
                     body.idempotency_key, _now()),
                )
                return {"dataset": "api_synthetic", "id": knowledge_id,
                        "state": body.decision, "replayed": False,
                        "source_review_id": source_id}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada ou expirada") from exc


def assemble_context(connection, owner: str, mission_id: str, domain_id: str, max_chars: int) -> dict:
    """Read only approved, matching source snapshots in one authorized transaction."""
    rows = connection.execute(
                    """SELECT k.*, d.decision, d.knowledge_sha256,
                              d.source_review_id AS decision_source_review_id,
                              d.source_artifact_sha256
                       FROM mission_knowledge k LEFT JOIN mission_knowledge_decisions d
                         ON d.knowledge_id=k.id AND d.owner=k.owner
                       WHERE k.owner=? AND k.mission_id=? AND k.domain_id=?
                       ORDER BY k.created_at, k.id LIMIT 100""",
        (owner, mission_id, domain_id),
    ).fetchall()
    included, omitted = [], []
    total = 0
    for row in rows:
        reason = None
        if row["decision"] != "approved":
            reason = "aguardando_revisao" if row["decision"] is None else "rejeitado"
        elif _content_sha(row["content"]) != row["knowledge_sha256"]:
            reason = "integridade"
        else:
            source = _source_review(connection, row)
            if (not _valid_source(source) or source["id"] != row["decision_source_review_id"]
                    or source["artifact_sha256"] != row["source_artifact_sha256"]):
                reason = "fonte_desatualizada"
            elif total + len(row["content"]) > max_chars:
                reason = "limite_de_tamanho"
        if reason:
            omitted.append({"knowledge_id": row["id"], "reason": reason})
        else:
            included.append({"knowledge_id": row["id"], "content": row["content"],
                             "content_sha256": row["knowledge_sha256"],
                             "source_review_id": row["decision_source_review_id"],
                             "source_artifact_sha256": row["source_artifact_sha256"],
                             "domain_id": row["domain_id"], "fetched_at": row["created_at"]})
            total += len(row["content"])
    return {"dataset": "api_synthetic", "mission_id": mission_id,
            "domain_id": domain_id, "assembled_at": _now(),
            "max_chars": max_chars, "used_chars": total,
            "included": included, "omitted": omitted}


@router.get("/context/{mission_id}")
def context_bundle(mission_id: str, request: Request, max_chars: int = 3000) -> dict:
    session = _session_from(request)
    if not 1 <= max_chars <= 10000:
        raise HTTPException(status_code=422, detail="limite de contexto inválido")
    store = request.app.state.memory_store
    with store.transaction() as connection:
        mission = connection.execute(
            "SELECT id, domain_id FROM missions WHERE id=? AND owner=?",
            (mission_id, session.principal),
        ).fetchone()
    if mission is None:
        raise HTTPException(status_code=404, detail="missão ausente")
    try:
        with mission_read_confirmed(session.principal, mission["domain_id"], session.token):
            with store.transaction() as connection:
                return assemble_context(connection, session.principal, mission_id,
                                        mission["domain_id"], max_chars)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão de leitura revogada ou expirada") from exc
