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
from source_admission import (
    canonical_knowledge_decision, canonical_review_state, knowledge_source_review,
    resolve_trusted_knowledge_projection, verified_source_for_knowledge,
)

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
    return knowledge_source_review(connection, row)


def _source_content_matches(connection, row, source) -> bool:
    if source is None:
        return False
    provenance = resolve_trusted_knowledge_projection(connection, row)
    if (
        not provenance.trusted
        or provenance.source_review is None
        or provenance.source_review["id"] != source["id"]
    ):
        return False
    if provenance.origin_type == "skill_derived":
        # The resolver has reproduced the producer's exact knowledge bytes.
        return provenance.artifact is not None
    if provenance.origin_type == "selected_original":
        try:
            snapshot = json.loads(source["artifact_snapshot_json"])
            return snapshot.get("content") == row["content"]
        except (TypeError, ValueError, AttributeError):
            return False
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
                    f"""SELECT k.id, k.owner, k.mission_id, k.domain_id, k.content, k.skill_version,
                           k.kind, k.source_review_id, k.created_at
                    FROM mission_knowledge k
                    WHERE k.owner=? AND k.domain_id IN ({placeholders})
                    ORDER BY k.created_at DESC, k.id LIMIT 100""",
                    (session.principal, *domains),
                ).fetchall()
                items = []
                for row in rows:
                    item = dict(row)
                    provenance = resolve_trusted_knowledge_projection(connection, row, session.principal)
                    state, decision_valid, decision_row = canonical_knowledge_decision(connection, row)
                    if not decision_valid or not provenance.trusted:
                        item["content"] = ""
                        item["state"] = "quarantined"
                        item["content_withheld"] = True
                        item["origin_verified"] = False
                        item["origin_type"] = None
                        item["classification"] = "unverified"
                        item["can_approve"] = False
                        item["can_use_context"] = False
                        item["can_feed_skill"] = False
                        item["source_review_id"] = None
                        item["source_artifact_sha256"] = None
                        item["decision"] = None
                        item["decided_at"] = None
                        item["decision_source_review_id"] = None
                        item["content_sha256"] = None
                        item["decision_state_proven"] = False
                    else:
                        item["decision"] = state if state in {"approved", "rejected"} else None
                        item["state"] = state
                        item["content_withheld"] = False
                        item["origin_verified"] = True
                        item["origin_type"] = provenance.origin_type
                        item["classification"] = "synthetic_verified"
                        item["can_approve"] = (
                            state == "staged"
                            and decision_row is None
                            and provenance.source_review_state == "approved"
                        )
                        item["can_use_context"] = state == "approved" and decision_row is not None
                        item["can_feed_skill"] = item["can_use_context"]
                        item["source_review_id"] = provenance.source_review["id"]
                        item["source_artifact_sha256"] = provenance.source_review["artifact_sha256"]
                        item["decision_state_proven"] = True
                        item["decided_at"] = decision_row["decided_at"] if decision_row else None
                        item["decision_source_review_id"] = decision_row["source_review_id"] if decision_row else None
                        item["content_sha256"] = _content_sha(row["content"])
                    items.append(item)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão de leitura revogada ou expirada") from exc
    return {"dataset": "api_synthetic", "items": items}


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
                if not verified_source_for_knowledge(connection, fresh):
                    raise HTTPException(status_code=409, detail="fonte em quarentena ou sem proveniência verificável")
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
                source_state, source_valid, _ = canonical_review_state(connection, source) if source else ("pending", False, None)
                if body.decision == "approved" and (not source_valid or source_state != "approved"
                                                    or not _source_content_matches(connection, fresh, source)):
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
        decision_state, decision_valid, decision_row = canonical_knowledge_decision(connection, row)
        if not decision_valid:
            if row["kind"] == "selected_original":
                reason = "fonte_em_quarentena"
            else:
                source = _source_review(connection, row)
                source_state, source_valid, _ = canonical_review_state(connection, source) if source else ("pending", False, None)
                reason = "fonte_desatualizada" if source and (not source_valid or source_state != "approved") else "integridade"
        elif decision_state != "approved":
            reason = "aguardando_revisao" if decision_state == "staged" else "rejeitado"
        elif _content_sha(row["content"]) != row["knowledge_sha256"]:
            reason = "integridade"
        elif not verified_source_for_knowledge(connection, row):
            reason = "fonte_em_quarentena"
        else:
            source = _source_review(connection, row)
            source_state, source_valid, _ = canonical_review_state(connection, source) if source else ("pending", False, None)
            if (not source_valid or source_state != "approved" or not _source_content_matches(connection, row, source)
                    or source["id"] != decision_row["source_review_id"]
                    or source["artifact_sha256"] != decision_row["source_artifact_sha256"]):
                reason = "fonte_desatualizada"
            elif total + len(row["content"]) > max_chars:
                reason = "limite_de_tamanho"
        if reason:
            omitted.append({"knowledge_id": row["id"], "reason": reason})
        else:
            included.append({"knowledge_id": row["id"], "content": row["content"],
                             "content_sha256": row["knowledge_sha256"],
                             "source_review_id": decision_row["source_review_id"],
                             "source_artifact_sha256": decision_row["source_artifact_sha256"],
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
