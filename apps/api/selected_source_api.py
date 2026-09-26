"""Explicit, local ingestion of a user-selected synthetic text file."""

from __future__ import annotations

import hashlib
import json
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from local_security import _session_from, mission_read_confirmed, mission_write_confirmed
from mission_repository import MissionCorrupt, MissionRepository, _now, _record_from_row, _token

router = APIRouter(prefix="/real/missions", tags=["selected-synthetic-sources"])


class SelectedSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=5, max_length=120)
    content: str = Field(min_length=1, max_length=50000)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=160)
    confirm_synthetic: bool


def _mission(connection, mission_id: str, owner: str):
    row = connection.execute(
        "SELECT * FROM missions WHERE id=? AND owner=?", (mission_id, owner),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="missão ausente")
    if not row["domain_id"]:
        raise HTTPException(status_code=409, detail="domínio da missão ausente")
    return row


@router.get("/{mission_id}/sources")
def list_selected_sources(mission_id: str, request: Request) -> dict:
    session = _session_from(request)
    store = request.app.state.memory_store
    with store.transaction() as connection:
        row = _mission(connection, mission_id, session.principal)
        domain = row["domain_id"]
    try:
        with mission_read_confirmed(session.principal, domain, session.token):
            with store.transaction() as connection:
                _mission(connection, mission_id, session.principal)
                items = connection.execute(
                    """SELECT id, mission_id, domain_id, display_name, content_sha256,
                              byte_count, classification, state, selected_at
                       FROM selected_synthetic_sources WHERE mission_id=? AND owner=?
                       ORDER BY selected_at, id LIMIT 100""",
                    (mission_id, session.principal),
                ).fetchall()
                return {"dataset": "api_synthetic", "items": [dict(item) for item in items]}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada") from exc


@router.post("/{mission_id}/sources", status_code=201)
def add_selected_source(mission_id: str, body: SelectedSourceIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    if not body.confirm_synthetic:
        raise HTTPException(status_code=422, detail="confirmação de conteúdo fictício obrigatória")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,115}\.(?:txt|md|json)", body.display_name):
        raise HTTPException(status_code=422, detail="nome de arquivo inválido")
    size = len(body.content.encode("utf-8"))
    if not 1 <= size <= 50000 or "\x00" in body.content:
        raise HTTPException(status_code=422, detail="arquivo fora do limite")
    digest = hashlib.sha256(body.content.encode("utf-8")).hexdigest()
    if digest != body.expected_content_sha256:
        raise HTTPException(status_code=409, detail="hash do arquivo divergente")
    store = request.app.state.memory_store
    with store.transaction() as connection:
        domain = _mission(connection, mission_id, session.principal)["domain_id"]
    try:
        with mission_write_confirmed(session.principal, domain, session.token):
            with store.transaction() as connection:
                row = _mission(connection, mission_id, session.principal)
                if row["domain_id"] != domain:
                    raise HTTPException(status_code=409, detail="domínio da missão alterado")
                existing = connection.execute(
                    "SELECT * FROM selected_synthetic_sources WHERE owner=? AND idempotency_key=?",
                    (session.principal, body.idempotency_key),
                ).fetchone()
                if existing is not None:
                    if (existing["mission_id"] != mission_id or existing["content_sha256"] != digest
                            or existing["display_name"] != body.display_name):
                        raise HTTPException(status_code=409, detail="idempotência reutilizada com corpo diferente")
                    return {"dataset": "api_synthetic", "id": existing["id"],
                            "mission_id": mission_id, "content_sha256": digest, "replayed": True}
                if row["status"] == "cancelled":
                    raise HTTPException(status_code=409, detail="missão cancelada")
                if connection.execute(
                    "SELECT id FROM selected_synthetic_sources WHERE owner=? AND mission_id=? AND content_sha256=?",
                    (session.principal, mission_id, digest),
                ).fetchone() is not None:
                    raise HTTPException(status_code=409, detail="arquivo já selecionado para a missão")
                try:
                    record = _record_from_row(row)
                except MissionCorrupt as exc:
                    raise HTTPException(status_code=409, detail="integridade da missão") from exc
                mission = record["mission"]
                now = _now()
                source_id = _token("source")
                artifact = {
                    "id": _token("artifact_selected"), "kind": "evidence",
                    "title": f"Fonte sintética selecionada: {body.display_name}",
                    "content": body.content, "skill_version": "1.0.0",
                    "skill_id": "selected-synthetic-file", "input_digest": digest,
                    "review_state": "draft", "reviewed_at": None,
                    "source_refs": [{"source_id": f"synthetic:selected:{source_id}", "uri": None,
                                     "observed_at": now, "last_verified_at": now,
                                     "valid_until": None, "domain_id": domain}],
                    "created_at": now,
                }
                mission["artifacts"].append(artifact)
                repo = MissionRepository(store)
                review_id = repo._sync_artifact_review(connection, mission, session.principal, artifact, now)
                repo._append_event(connection, mission, session.principal, "artifact_created", None,
                                   "Fonte sintética selecionada; aguarda revisão.", now)
                mission["updated_at"] = now
                connection.execute(
                    "UPDATE missions SET document_json=?, revision=revision+1, updated_at=? WHERE id=? AND owner=?",
                    (json.dumps(mission, ensure_ascii=False), now, mission_id, session.principal),
                )
                connection.execute(
                    """INSERT INTO selected_synthetic_sources
                       (id, owner, mission_id, domain_id, display_name, content_sha256,
                        idempotency_key, byte_count, classification, state, selected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'synthetic_test_only', 'awaiting_review', ?)""",
                    (source_id, session.principal, mission_id, domain, body.display_name, digest,
                     body.idempotency_key, size, now),
                )
                connection.execute(
                    """INSERT INTO mission_knowledge
                       (id, owner, mission_id, domain_id, state, content, skill_version,
                        created_at, kind, source_review_id)
                       VALUES (?, ?, ?, ?, 'staged', ?, '1.0.0', ?, 'selected_original', ?)""",
                    (_token("knowledge_selected"), session.principal, mission_id, domain,
                     body.content, now, review_id),
                )
                return {"dataset": "api_synthetic", "id": source_id, "mission_id": mission_id,
                        "content_sha256": digest, "review_id": review_id, "replayed": False}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada") from exc
