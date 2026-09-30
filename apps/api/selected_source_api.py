"""Explicit admission of versioned, server-owned synthetic source fixtures."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from local_security import _session_from, mission_read_confirmed, mission_write_confirmed
from mission_repository import MissionCorrupt, MissionRepository, _now, _record_from_row, _token
from source_admission import (
    canonical_knowledge_decision, canonical_review_state,
    resolve_trusted_source_projection, prove_source,
)
from source_catalog import CATALOG_ID, CATALOG_VERSION, fixture_for, public_fixtures

router = APIRouter(prefix="/real/missions", tags=["selected-synthetic-sources"])


class SelectedSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    idempotency_key: str = Field(min_length=8, max_length=160)


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
                    """SELECT s.*
                       FROM selected_synthetic_sources s
                       WHERE s.mission_id=? AND s.owner=?
                       ORDER BY s.selected_at, s.id LIMIT 100""",
                    (mission_id, session.principal),
                ).fetchall()
                safe_items = []
                for item in items:
                    projection = resolve_trusted_source_projection(
                        connection, session.principal, mission_id, source_id=item["id"],
                    )
                    proof = projection.proof
                    if not projection.trusted or proof is None:
                        safe_items.append({
                            "id": item["id"], "mission_id": mission_id,
                            "classification": "unverified", "selection_state": "quarantined",
                            "artifact_review_state": "pending", "knowledge_state": "quarantined",
                            "display_name": "Fonte retida para verificação",
                            "content_withheld": True, "fixture_id": None,
                            "catalog_id": None, "catalog_version": None,
                            "content_sha256": None, "fixture_sha256": None,
                            "byte_count": None, "provenance": None,
                            "review_id": None, "knowledge_id": None,
                            "selected_at": item["selected_at"],
                        })
                        continue
                    review_state, review_valid, _ = canonical_review_state(connection, proof.review)
                    knowledge_state, knowledge_valid, _ = canonical_knowledge_decision(
                        connection, proof.knowledge
                    )
                    if not review_valid or not knowledge_valid:
                        safe_items.append({
                            "id": item["id"], "mission_id": mission_id,
                            "classification": "unverified", "selection_state": "quarantined",
                            "artifact_review_state": "pending", "knowledge_state": "quarantined",
                            "display_name": "Fonte retida para verificação",
                            "content_withheld": True, "fixture_id": None,
                            "catalog_id": None, "catalog_version": None,
                            "content_sha256": None, "fixture_sha256": None,
                            "byte_count": None, "provenance": None,
                            "review_id": None, "knowledge_id": None,
                            "selected_at": item["selected_at"],
                        })
                        continue
                    safe = {
                        "id": item["id"], "mission_id": mission_id,
                        "domain_id": item["domain_id"], "display_name": proof.fixture["display_name"],
                        "content_sha256": proof.fixture["content_sha256"],
                        "byte_count": len(proof.fixture["content"].encode("utf-8")),
                        "classification": "synthetic_verified", "selection_state": "selected",
                        "fixture_id": proof.fixture["id"], "catalog_id": CATALOG_ID,
                        "catalog_version": CATALOG_VERSION,
                        "fixture_sha256": proof.fixture["content_sha256"],
                        "provenance": dict(proof.fixture["provenance"]),
                        "review_id": proof.review["id"], "knowledge_id": proof.knowledge["id"],
                        "artifact_review_state": review_state,
                        "knowledge_state": knowledge_state,
                        "content_withheld": False, "selected_at": item["selected_at"],
                    }
                    safe_items.append(safe)
                return {"dataset": "api_synthetic", "items": safe_items}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada") from exc


@router.get("/source-catalog/fixtures")
def list_source_fixtures(request: Request) -> dict:
    _session_from(request)
    return {"dataset": "api_synthetic", "catalog_id": CATALOG_ID,
            "catalog_version": CATALOG_VERSION, "items": public_fixtures()}


@router.post("/{mission_id}/sources", status_code=201)
def add_selected_source(mission_id: str, body: SelectedSourceIn, request: Request) -> dict:
    session = _session_from(request, mutation=True)
    fixture = fixture_for(body.fixture_id)
    if fixture is None:
        raise HTTPException(status_code=422, detail="fixture sintética indisponível")
    canonical_name = fixture["display_name"]
    canonical_content = fixture["content"]
    digest = fixture["content_sha256"]
    size = len(canonical_content.encode("utf-8"))
    provenance_json = json.dumps(fixture["provenance"], ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":"))
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
                            or existing["fixture_id"] != fixture["id"]
                            or existing["classification"] != "synthetic_verified"
                            or existing["state"] != "selected"
                            or not resolve_trusted_source_projection(
                                connection, session.principal, mission_id,
                                source_id=existing["id"],
                            ).trusted):
                        raise HTTPException(status_code=409, detail="idempotência reutilizada com corpo diferente")
                    return {"dataset": "api_synthetic", "id": existing["id"],
                            "mission_id": mission_id, "fixture_id": fixture["id"],
                            "content_sha256": digest, "replayed": True}
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
                    "title": f"Fonte sintética selecionada: {canonical_name}",
                    "content": canonical_content, "skill_version": "1.0.0",
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
                knowledge_id = _token("knowledge_selected")
                connection.execute(
                    """INSERT INTO mission_knowledge
                       (id, owner, mission_id, domain_id, state, content, skill_version,
                        created_at, kind, source_review_id)
                       VALUES (?, ?, ?, ?, 'staged', ?, '1.0.0', ?, 'selected_original', ?)""",
                    (knowledge_id, session.principal, mission_id, domain,
                     canonical_content, now, review_id),
                )
                connection.execute(
                    """INSERT INTO selected_synthetic_sources
                       (id, owner, mission_id, domain_id, display_name, content_sha256,
                        review_id, knowledge_id, idempotency_key, byte_count,
                        classification, state, selected_at, fixture_id, catalog_id,
                        catalog_version, fixture_sha256, provenance_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synthetic_verified', 'selected', ?, ?, ?, ?, ?, ?)""",
                    (source_id, session.principal, mission_id, domain, canonical_name, digest,
                     review_id, knowledge_id, body.idempotency_key, size, now, fixture["id"],
                     CATALOG_ID, CATALOG_VERSION, digest, provenance_json),
                )
                if not prove_source(connection, source_id, session.principal, mission_id).trusted:
                    raise HTTPException(status_code=503, detail="não foi possível validar a fonte local")
                return {"dataset": "api_synthetic", "id": source_id, "mission_id": mission_id,
                        "fixture_id": fixture["id"], "content_sha256": digest,
                        "review_id": review_id, "replayed": False}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão ou sessão revogada") from exc
