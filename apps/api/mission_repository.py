"""Transactional synthetic mission persistence inside the existing SQLite store."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mission_contracts import validate_contract
from synthetic_skill import capture_and_classify

MAX_TASKS = 20
MAX_TITLE = 240
PAGE_LIMIT = 20

IDEMPOTENCY_LEGACY_UNRESOLVED = "legacy_unresolved"
IDEMPOTENCY_CREATE = "mission.create"
IDEMPOTENCY_TRANSITION = "mission.transition"
IDEMPOTENCY_IMPORT = "mission.import"
IDEMPOTENCY_IMPORT_ITEM = "mission.import.item"
IDEMPOTENCY_REVIEW_DECISION = "mission.review.decide"
IDEMPOTENCY_REVIEW_REVISION = "mission.review.revise"


class MissionConflict(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


class MissionRejected(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


class MissionCorrupt(Exception):
    def __init__(self, mission_id: str) -> None:
        self.mission_id = mission_id


class MissionDenied(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


def _find_idempotency(connection, owner: str, operation: str, idempotency_key: str):
    legacy = connection.execute(
        "SELECT 1 FROM mission_idempotency WHERE owner=? AND operation=? AND idempotency_key=?",
        (owner, IDEMPOTENCY_LEGACY_UNRESOLVED, idempotency_key),
    ).fetchone()
    if legacy is not None:
        raise MissionConflict("chave de idempotência legada exige reconciliação")
    return connection.execute(
        "SELECT mission_id, body_sha256, result_json FROM mission_idempotency "
        "WHERE owner=? AND operation=? AND idempotency_key=?",
        (owner, operation, idempotency_key),
    ).fetchone()


def _store_idempotency(
    connection,
    owner: str,
    operation: str,
    idempotency_key: str,
    mission_id: str,
    body_sha256: str,
    result_json: str | None = None,
) -> None:
    if _find_idempotency(connection, owner, operation, idempotency_key) is not None:
        raise MissionConflict("chave de idempotência já utilizada nesta operação")
    connection.execute(
        "INSERT INTO mission_idempotency "
        "(owner, operation, idempotency_key, mission_id, body_sha256, result_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (owner, operation, idempotency_key, mission_id, body_sha256, result_json),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pause_review_if_requested() -> None:
    raw = os.environ.get("JARVIS_TEST_PAUSE_REVIEW_FILE")
    if not raw:
        return
    path = Path(raw)
    path.write_text("open", encoding="utf-8")
    deadline = time.time() + 30
    while time.time() < deadline:
        if path.read_text(encoding="utf-8") == "go":
            return
        time.sleep(0.05)


def _token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _acyclic(tasks: list[dict]) -> None:
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise MissionRejected("etapa duplicada")
    graph = {task["id"]: list(task.get("depends_on") or []) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise MissionRejected("dependência cíclica")
        if task_id not in graph:
            raise MissionRejected("dependência desconhecida")
        visiting.add(task_id)
        for dependency in graph[task_id]:
            walk(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        walk(task_id)


def _check_mission(document: dict) -> None:
    if len(document.get("tasks") or []) > MAX_TASKS:
        raise MissionRejected("limite de etapas excedido")
    if len(document.get("title") or "") > MAX_TITLE:
        raise MissionRejected("título excede o limite")
    try:
        validate_contract("Mission", document)
    except ValueError as exc:
        raise MissionRejected("missão malformada") from exc
    event_ids = [event["id"] for event in document["events"]]
    event_keys = [event["idempotency_key"] for event in document["events"]]
    if len(event_ids) != len(set(event_ids)):
        raise MissionRejected("ID de evento repetido no documento")
    if len(event_keys) != len(set(event_keys)):
        raise MissionRejected("chave de evento repetida no documento")
    _acyclic(list(document["tasks"]))
    if document["status"] == "done" and any(task["status"] != "done" for task in document["tasks"]):
        raise MissionRejected("missão concluída sem etapas concluídas")


def _canonical_import_document(document: dict) -> dict:
    """Remove imported review authority before creating local pending reviews."""
    clean = json.loads(json.dumps(document, ensure_ascii=False))
    for artifact in clean.get("artifacts", []):
        state = artifact.get("review_state")
        if state in {"approved", "rejected", "changes_requested", "approved_locally", "not_required"}:
            raise MissionRejected("documento importado declara decisão de revisão sem ledger local")
        # Pending/draft/review labels are also client claims. Imported artifacts
        # always enter the local queue as drafts with a fresh pending review row.
        artifact["review_state"] = "draft"
        artifact["reviewed_at"] = None
    return clean


def new_mission(title: str, domain_id: str, owner: str) -> dict:
    now = _now()
    mission_id = _token("mission")
    tasks = []
    previous = None
    for task_id, label in (
        ("task_capture", "Capturar e classificar entradas sintéticas"),
        ("task_context", "Montar contexto autorizado"),
        ("task_report", "Gerar rascunho com evidências"),
    ):
        tasks.append({
            "id": task_id,
            "title": label,
            "status": "planned",
            "depends_on": [previous] if previous else [],
            "attempt": 1,
            "idempotency_key": f"{mission_id}:{task_id}:1",
            "updated_at": now,
            "failure_reason": None,
        })
        previous = task_id
    document = {
        "schema_version": 1,
        "id": mission_id,
        "title": title.strip()[:MAX_TITLE],
        "description": "Missão sintética persistida na API local. Sem chamada externa.",
        "status": "planned",
        "domain_id": domain_id,
        "tasks": tasks,
        "checkpoints": [{
            "id": _token("checkpoint"),
            "task_id": None,
            "state": "created",
            "note": "Criada no servidor sintético.",
            "created_at": now,
        }],
        "events": [{
            "id": _token("event"),
            "type": "mission_created",
            "message": "Missão sintética criada.",
            "task_id": None,
            "created_at": now,
            "idempotency_key": f"{mission_id}:created",
        }],
        "artifacts": [],
        "budget": {"cap": 0, "spent": 0},
        "created_at": now,
        "updated_at": now,
    }
    _check_mission(document)
    return {
        "dataset": "api_synthetic",
        "owner": owner,
        "revision": 1,
        "access_class": "synthetic_local",
        "mission": document,
    }


def _record_from_row(row) -> dict:
    try:
        mission = json.loads(row["document_json"])
        validate_contract("Mission", mission)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise MissionCorrupt(row["id"]) from exc
    return {
        "dataset": "api_synthetic",
        "owner": row["owner"],
        "revision": row["revision"],
        "access_class": "synthetic_local",
        "mission": mission,
    }


class MissionRepository:
    def __init__(self, store) -> None:
        self.store = store

    def create(self, owner: str, title: str, domain_id: str, idempotency_key: str) -> tuple[dict, bool]:
        body_hash = _sha({"title": title, "domain_id": domain_id})
        with self.store.transaction() as connection:
            existing = _find_idempotency(connection, owner, IDEMPOTENCY_CREATE, idempotency_key)
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                row = connection.execute("SELECT * FROM missions WHERE id=? AND owner=?", (existing["mission_id"], owner)).fetchone()
                if row is None:
                    raise MissionRejected("registro de idempotência órfão")
                return _record_from_row(row), True
            record = new_mission(title, domain_id, owner)
            self._insert_record(connection, record, owner, idempotency_key, body_hash, IDEMPOTENCY_CREATE)
            return record, False

    def get(self, owner: str, mission_id: str) -> dict | None:
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM missions WHERE id=? AND owner=?",
                (mission_id, owner),
            ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def list_page(self, owner: str, domain_id: str | None, limit: int, cursor: str | None,
                  allowed_domains: frozenset[str] | set[str] | None = None) -> dict:
        limit = min(max(limit, 1), PAGE_LIMIT)
        clauses = ["owner=?"]
        params: list[Any] = [owner]
        if allowed_domains is not None:
            domains = sorted(allowed_domains)
            if not domains:
                return {"dataset": "api_synthetic", "items": [], "corrupt": [], "next_cursor": None}
            clauses.append(f"domain_id IN ({','.join('?' for _ in domains)})")
            params.extend(domains)
        if domain_id is not None:
            clauses.append("domain_id=?")
            params.append(domain_id)
        if cursor:
            clauses.append("id>?")
            params.append(cursor)
        params.append(limit + 1)
        with self.store.transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM missions WHERE {' AND '.join(clauses)} ORDER BY id LIMIT ?",
                params,
            ).fetchall()
        page = rows[:limit]
        next_cursor = page[-1]["id"] if len(rows) > limit and page else None
        items = []
        corrupt = []
        for row in page:
            try:
                items.append(_record_from_row(row))
            except MissionCorrupt:
                corrupt.append({"id": row["id"], "domain_id": row["domain_id"], "integrity": "corrupt"})
        return {"dataset": "api_synthetic", "items": items, "corrupt": corrupt, "next_cursor": next_cursor}

    def transition(self, owner: str, mission_id: str, action: str, expected_revision: int,
                   idempotency_key: str, session_token: str | None = None) -> dict:
        if action in {"run_next", "resume"}:
            from mission_engine import MissionEngine
            return MissionEngine(self).run(owner, mission_id, action, expected_revision,
                                           idempotency_key, session_token)
        body_hash = _sha({"action": action, "mission_id": mission_id, "expected_revision": expected_revision})
        with self.store.transaction() as connection:
            existing = _find_idempotency(connection, owner, IDEMPOTENCY_TRANSITION, idempotency_key)
            if existing is not None:
                if existing["body_sha256"] != body_hash or existing["mission_id"] != mission_id:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                row = connection.execute("SELECT * FROM missions WHERE id=? AND owner=?", (mission_id, owner)).fetchone()
                if row is None:
                    raise MissionRejected("registro ausente")
                return _record_from_row(row)
            row = connection.execute(
                "SELECT * FROM missions WHERE id=? AND owner=?",
                (mission_id, owner),
            ).fetchone()
            if row is None:
                raise MissionRejected("registro ausente")
            if row["revision"] != expected_revision:
                raise MissionConflict("revisão divergente")
            record = _record_from_row(row)
            updated = self._apply(connection, record, action, owner)
            connection.execute(
                "UPDATE missions SET status=?, revision=?, document_json=?, updated_at=? WHERE id=? AND owner=? AND revision=?",
                (
                    updated["mission"]["status"],
                    updated["revision"],
                    json.dumps(updated["mission"], ensure_ascii=False),
                    updated["mission"]["updated_at"],
                    mission_id,
                    owner,
                    expected_revision,
                ),
            )
            _store_idempotency(
                connection, owner, IDEMPOTENCY_TRANSITION, idempotency_key, mission_id, body_hash,
            )
            return updated

    def _apply(self, connection, record: dict, action: str, owner: str) -> dict:
        mission = json.loads(json.dumps(record["mission"]))
        now = _now()
        if action == "cancel":
            if mission["status"] in {"done", "cancelled"}:
                raise MissionRejected("cancelamento não se aplica a este estado")
            mission["status"] = "cancelled"
            for task in mission["tasks"]:
                if task["status"] not in {"done", "failed", "cancelled"}:
                    task["status"] = "cancelled"
                    task["updated_at"] = now
            self._append_event(connection, mission, owner, "mission_cancelled", None, "Missão cancelada no servidor.", now)
            connection.execute(
                "UPDATE mission_executions SET phase='failed', committed_at=? WHERE mission_id=? AND owner=? AND phase='open'",
                (now, mission["id"], owner),
            )
        elif action == "fail":
            if mission["status"] not in {"running", "interrupted", "planned"}:
                raise MissionRejected("falha não se aplica a este estado")
            task = next((item for item in mission["tasks"] if item["status"] in {"running", "planned", "blocked"}), None)
            if task is None:
                raise MissionRejected("não há etapa para falhar")
            task["status"] = "failed"
            task["failure_reason"] = "falha explícita do executor local"
            task["updated_at"] = now
            mission["status"] = "failed"
            self._append_event(connection, mission, owner, "task_failed", task["id"], "Etapa marcada como falha pelo executor.", now)
            connection.execute(
                "UPDATE mission_executions SET phase='failed', committed_at=? WHERE mission_id=? AND owner=? AND phase='open'",
                (now, mission["id"], owner),
            )
        elif action == "retry":
            if mission["status"] != "failed":
                raise MissionRejected("retry exige missão falha")
            task = next((item for item in mission["tasks"] if item["status"] == "failed"), None)
            if task is None or task["attempt"] >= 3:
                raise MissionRejected("limite de tentativas")
            task["attempt"] += 1
            task["status"] = "planned"
            task["failure_reason"] = None
            task["updated_at"] = now
            mission["status"] = "planned"
            self._append_event(connection, mission, owner, "task_retried", task["id"], f"Tentativa {task['attempt']} preparada.", now)
        elif action == "run_next":
            if mission["status"] in {"cancelled", "failed", "done"}:
                raise MissionRejected("execução não se aplica a este estado")
            task = next((
                item for item in mission["tasks"]
                if item["status"] in {"planned", "blocked"}
                and all(any(dep["id"] == dependency and dep["status"] == "done" for dep in mission["tasks"]) for dependency in item["depends_on"])
            ), None)
            if task is None:
                if all(item["status"] == "done" for item in mission["tasks"]):
                    mission["status"] = "done"
                else:
                    raise MissionRejected("nenhuma etapa executável")
            else:
                task["status"] = "done"
                task["updated_at"] = now
                self._append_event(connection, mission, owner, "task_completed", task["id"], f"Etapa determinística concluída: {task['title']}.", now)
                if task["id"] == "task_capture":
                    artifact, knowledge = capture_and_classify(mission["title"], mission["domain_id"], now, mission["id"])
                    mission["artifacts"].append(artifact)
                    connection.execute(
                        "INSERT INTO mission_knowledge(id, owner, mission_id, domain_id, state, content, skill_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (knowledge["id"], owner, mission["id"], knowledge["domain_id"], knowledge["state"], knowledge["content"], knowledge["skill_version"], now),
                    )
                    self._append_event(connection, mission, owner, "artifact_created", task["id"], "Artefato draft criado por código determinístico.", now)
                elif task["id"] == "task_context":
                    mission["artifacts"].append(self._draft_artifact(
                        mission, now, "context_bundle", "Pacote de contexto sintético",
                        "Minimização determinística no servidor. Não concede acesso e não consulta fonte não autorizada.",
                    ))
                    self._append_event(connection, mission, owner, "artifact_created", task["id"], "Contexto sintético registrado como rascunho.", now)
                elif task["id"] == "task_report":
                    mission["artifacts"].append(self._draft_artifact(
                        mission, now, "report", f"Rascunho: {mission['title'][:80]}",
                        "Rascunho determinístico aguardando revisão humana. Nenhuma aprovação foi marcada.",
                    ))
                    self._append_event(connection, mission, owner, "artifact_created", task["id"], "Rascunho criado sem aprovação automática.", now)
                mission["status"] = "done" if all(item["status"] == "done" for item in mission["tasks"]) else "running"
        else:
            raise MissionRejected("ação desconhecida")
        mission["updated_at"] = now
        _check_mission(mission)
        record["mission"] = mission
        record["revision"] = record["revision"] + 1
        return record

    def _draft_artifact(self, mission: dict, now: str, kind: str, title: str, content: str) -> dict:
        return {
            "id": _token("artifact"),
            "kind": kind,
            "title": title,
            "content": content,
            "skill_version": "1.0.0",
            "review_state": "draft",
            "reviewed_at": None,
            "source_refs": [{
                "source_id": f"synthetic:mission:{mission['id']}",
                "uri": None,
                "observed_at": now,
                "last_verified_at": now,
                "valid_until": None,
                "domain_id": mission["domain_id"],
            }],
            "created_at": now,
        }

    def _append_event(self, connection, mission: dict, owner: str, event_type: str, task_id: str | None, message: str, now: str, stable_key: str | None = None) -> None:
        event_id = _token("event")
        key = stable_key or f"{mission['id']}:{event_type}:{event_id}"
        if any(item.get("idempotency_key") == key for item in mission["events"]):
            return
        mission["events"].append({
            "id": event_id,
            "type": event_type,
            "message": message[:1000],
            "task_id": task_id,
            "created_at": now,
            "idempotency_key": key,
        })
        connection.execute(
            "INSERT INTO mission_events(id, mission_id, owner, event_type, actor, correlation_id, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, mission["id"], owner, event_type, owner, key, key, now),
        )

    def _insert_record(
        self,
        connection,
        record: dict,
        owner: str,
        idempotency_key: str,
        body_hash: str,
        idempotency_operation: str,
    ) -> None:
        mission = record["mission"]
        connection.execute(
            "INSERT INTO missions(id, owner, domain_id, status, revision, document_json, dataset, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'api_synthetic', ?, ?)",
            (mission["id"], owner, mission["domain_id"], mission["status"], record["revision"], json.dumps(mission, ensure_ascii=False), mission["created_at"], mission["updated_at"]),
        )
        for event in mission["events"]:
            connection.execute(
                "INSERT INTO mission_events(id, mission_id, owner, event_type, actor, correlation_id, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event["id"], mission["id"], owner, event["type"], owner, event["idempotency_key"], event["idempotency_key"], event["created_at"]),
            )
        _store_idempotency(
            connection, owner, idempotency_operation, idempotency_key, mission["id"], body_hash,
        )
        for artifact in mission.get("artifacts", []):
            self._sync_artifact_review(connection, mission, owner, artifact, mission["created_at"])

    def _sync_artifact_review(self, connection, mission: dict, owner: str, artifact: dict, now: str) -> str:
        review_id = f"rev_{artifact['id']}_1"
        artifact_sha = _sha(artifact)
        domain_id = mission.get("domain_id") or "dom_synthetic_a"
        connection.execute(
            """INSERT OR IGNORE INTO mission_artifact_reviews (
                id, mission_id, owner, artifact_id, artifact_version,
                artifact_sha256, domain_id, state, decision_reason,
                decision_actor, decided_at, revision, created_at, updated_at,
                artifact_snapshot_json
            ) VALUES (?, ?, ?, ?, 1, ?, ?, 'pending', NULL, NULL, NULL, 1, ?, ?, ?)""",
            (review_id, mission["id"], owner, artifact["id"], artifact_sha, domain_id, now, now,
             json.dumps(artifact, ensure_ascii=False)),
        )
        return review_id

    def import_valid(self, owner: str, documents: list[dict], idempotency_key: str) -> dict:
        accepted = []
        quarantined = []
        valid_documents = []
        for index, document in enumerate(documents):
            try:
                _check_mission(document)
                if document.get("domain_id") is None:
                    raise MissionRejected("domínio ausente")
                document = _canonical_import_document(document)
            except MissionRejected as exc:
                quarantined.append({"index": index, "reason": exc.detail})
                continue
            valid_documents.append(document)

        mission_ids = [document["id"] for document in valid_documents]
        event_ids = [event["id"] for document in valid_documents for event in document["events"]]
        if len(mission_ids) != len(set(mission_ids)) or len(event_ids) != len(set(event_ids)):
            raise MissionRejected("lote de importação contém identificadores repetidos")

        if quarantined and len(quarantined) == len(documents):
            return {"dataset": "api_synthetic", "accepted": [], "quarantined": quarantined}
        body_hash = _sha({"scope": "mission_import", "owner": owner, "documents": documents})
        with self.store.transaction() as connection:
            existing = _find_idempotency(connection, owner, IDEMPOTENCY_IMPORT, idempotency_key)
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                if existing["result_json"]:
                    stored = json.loads(existing["result_json"])
                    stored["replayed"] = True
                    return stored
                return {"dataset": "api_synthetic", "accepted": [], "quarantined": quarantined, "replayed": True, "legacy": True}

            new_documents = []
            for document in valid_documents:
                found = connection.execute(
                    "SELECT owner, document_json FROM missions WHERE id=?",
                    (document["id"],),
                ).fetchone()
                if found is not None:
                    if found["owner"] != owner:
                        raise MissionConflict("conflito de identidade na importação")
                    try:
                        stored_document = json.loads(found["document_json"])
                    except (json.JSONDecodeError, TypeError):
                        raise MissionConflict("conflito de identidade na importação") from None
                    if _sha(stored_document) != _sha(document):
                        raise MissionConflict("conflito de identidade na importação")
                    continue

                for event in document["events"]:
                    used = connection.execute(
                        "SELECT 1 FROM mission_events WHERE id=? LIMIT 1",
                        (event["id"],),
                    ).fetchone()
                    if used is not None:
                        raise MissionConflict("conflito de identidade na importação")
                new_documents.append(document)

            for document in new_documents:
                record = {
                    "dataset": "api_synthetic",
                    "owner": owner,
                    "revision": 1,
                    "access_class": "synthetic_local",
                    "mission": document,
                }
                self._insert_record(
                    connection,
                    record,
                    owner,
                    f"{idempotency_key}:{document['id']}",
                    _sha(document),
                    IDEMPOTENCY_IMPORT_ITEM,
                )
                accepted.append(document["id"])
            result = {"dataset": "api_synthetic", "accepted": accepted, "quarantined": quarantined, "replayed": False}
            _store_idempotency(
                connection,
                owner,
                IDEMPOTENCY_IMPORT,
                idempotency_key,
                accepted[0] if accepted else "mission_import_empty",
                body_hash,
                json.dumps(result, ensure_ascii=False),
            )
        return result

    def list_reviews(
        self,
        owner: str,
        domain_id: str | None = None,
        state: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
        allowed_domains: frozenset[str] | set[str] | None = None,
    ) -> dict:
        clauses = ["r.owner = ?"]
        params: list[Any] = [owner]
        if allowed_domains is not None:
            domains = sorted(allowed_domains)
            if not domains:
                return {"dataset": "api_synthetic", "items": [], "corrupt": [], "next_cursor": None}
            clauses.append(f"r.domain_id IN ({','.join('?' for _ in domains)})")
            params.extend(domains)
        if domain_id is not None:
            clauses.append("r.domain_id = ?")
            params.append(domain_id)
        limit = max(1, min(limit, 100))
        query = f"""
            SELECT r.*, m.status as mission_status, m.document_json
            FROM mission_artifact_reviews r
            JOIN missions m ON m.id = r.mission_id AND m.owner = r.owner
            WHERE {' AND '.join(clauses)} AND r.id > ?
            ORDER BY r.id ASC LIMIT 250
        """
        with self.store.transaction() as connection:
            from source_admission import (
                canonical_review_state, redact_untrusted_source_artifact,
                review_is_unverified_source,
            )
            items = []
            corrupt = []
            scan_cursor = cursor or ""
            has_more = False
            while len(items) <= limit:
                rows = connection.execute(query, (*params, scan_cursor)).fetchall()
                if not rows:
                    break
                for row in rows:
                    scan_cursor = row["id"]
                    try:
                        mission_doc = json.loads(row["document_json"])
                        decision_state, decision_proven, artifact = canonical_review_state(connection, row)
                        quarantined = review_is_unverified_source(connection, owner, row["id"])
                        if artifact is None and not quarantined:
                            raise ValueError("snapshot da revisão inválido")
                        if quarantined:
                            decision_state, decision_proven = "pending", False
                            artifact = artifact or {"title": "Fonte retida para verificação", "kind": "evidence"}
                        if state is not None and decision_state != state:
                            continue
                        items.append({
                            "id": row["id"],
                            "mission_id": row["mission_id"],
                            "mission_title": mission_doc.get("title", "") if not quarantined else "Missão com fonte retida",
                            "mission_status": row["mission_status"],
                            "artifact_id": row["artifact_id"],
                            "artifact_version": row["artifact_version"],
                            "artifact_sha256": row["artifact_sha256"] if not quarantined else None,
                            "artifact_title": artifact.get("title", "") if not quarantined else "Fonte retida para verificação",
                            "artifact_kind": artifact.get("kind", "draft"),
                            "content_withheld": quarantined,
                            "classification": "unverified" if quarantined else None,
                            "decision_state_proven": decision_proven,
                            "domain_id": row["domain_id"],
                            "state": decision_state,
                            "decision_reason": row["decision_reason"] if decision_proven else None,
                            "decision_actor": row["decision_actor"] if decision_proven else None,
                            "decided_at": row["decided_at"] if decision_proven else None,
                            "revision": row["revision"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                        })
                        if len(items) > limit:
                            has_more = True
                            break
                    except Exception:
                        corrupt.append({"id": row["id"], "domain_id": row["domain_id"], "integrity": "corrupt"})
                if has_more or len(rows) < 250:
                    break
            next_cursor = items[limit - 1]["id"] if has_more and len(items) > limit else None
            return {"dataset": "api_synthetic", "items": items[:limit], "corrupt": corrupt,
                    "next_cursor": next_cursor}

    def get_review(self, owner: str, review_id: str) -> dict | None:
        query = """
            SELECT r.*, m.status as mission_status, m.document_json
            FROM mission_artifact_reviews r
            JOIN missions m ON m.id = r.mission_id AND m.owner = r.owner
            WHERE r.owner = ? AND r.id = ?
        """
        with self.store.transaction() as connection:
            row = connection.execute(query, (owner, review_id)).fetchone()
            if row is None:
                return None
            from source_admission import (
                canonical_review_state, redact_untrusted_source_artifact,
                review_is_unverified_source,
            )
            quarantined = review_is_unverified_source(connection, owner, review_id)
            try:
                mission_doc = json.loads(row["document_json"])
                artifact = json.loads(row["artifact_snapshot_json"]) if row["artifact_snapshot_json"] else None
                if artifact is not None and (_sha(artifact) != row["artifact_sha256"] or artifact.get("id") != row["artifact_id"]):
                    artifact = None
                if artifact is None and not quarantined:
                    raise ValueError("snapshot da revisão inválido")
            except Exception as exc:
                raise MissionCorrupt(review_id) from exc
            state, state_proven, _ = canonical_review_state(connection, row)
            if quarantined:
                state, state_proven = "pending", False
                artifact = artifact or {"id": row["artifact_id"], "kind": "evidence",
                                        "title": "Fonte retida para verificação", "content": ""}
            decisions = connection.execute(
                """SELECT id, decision, decision_reason, actor, idempotency_key, created_at
                   FROM mission_review_decisions
                   WHERE review_id = ? AND owner = ?
                   ORDER BY created_at ASC""",
                (review_id, owner),
            ).fetchall()
            history = [dict(d) for d in decisions] if state_proven else []
        return {
            "dataset": "api_synthetic",
            "id": row["id"],
            "mission_id": row["mission_id"],
            "mission_title": mission_doc.get("title", ""),
            "mission_status": row["mission_status"],
            "artifact_id": row["artifact_id"],
            "artifact_version": row["artifact_version"],
            "artifact_sha256": row["artifact_sha256"] if not quarantined else None,
            "artifact": (redact_untrusted_source_artifact(artifact)
                         if quarantined else artifact),
            "content_withheld": quarantined,
            "classification": "unverified" if quarantined else None,
            "decision_state_proven": state_proven,
            "domain_id": row["domain_id"],
            "state": state,
            "decision_reason": row["decision_reason"] if state_proven else None,
            "decision_actor": row["decision_actor"] if state_proven else None,
            "decided_at": row["decided_at"] if state_proven else None,
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "history": history,
            "history_withheld": quarantined or not state_proven,
        }

    def decide_review(
        self,
        owner: str,
        review_id: str,
        decision: str,
        expected_revision: int,
        expected_artifact_sha256: str,
        reason: str | None,
        idempotency_key: str,
        session_token: str | None = None,
    ) -> tuple[dict, bool]:
        if decision not in ("approved", "rejected", "changes_requested"):
            raise MissionRejected("decisão inválida")
        clean_reason = reason.strip() if reason else None
        if decision in ("rejected", "changes_requested") and not clean_reason:
            raise MissionRejected("motivo obrigatório para rejeição ou solicitação de ajustes")
        if clean_reason and len(clean_reason) > 500:
            raise MissionRejected("motivo excede limite de 500 caracteres")

        body_hash = _sha({
            "action": "decide_review",
            "review_id": review_id,
            "decision": decision,
            "expected_revision": expected_revision,
            "expected_artifact_sha256": expected_artifact_sha256,
            "reason": clean_reason,
        })

        with self.store.transaction() as connection:
            from source_admission import review_is_unverified_source
            if review_is_unverified_source(connection, owner, review_id):
                raise MissionRejected("fonte em quarentena ou sem proveniência verificável não pode ser revisada")
            existing = _find_idempotency(
                connection, owner, IDEMPOTENCY_REVIEW_DECISION, idempotency_key,
            )
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                if existing["result_json"]:
                    stored = json.loads(existing["result_json"])
                    stored["replayed"] = True
                    return stored, True
                rev = self.get_review(owner, review_id)
                if rev is not None:
                    rev["replayed"] = True
                    return rev, True
                raise MissionConflict("idempotência reutilizada com corpo diferente")

            rev_row = connection.execute(
                "SELECT domain_id FROM mission_artifact_reviews WHERE id=? AND owner=?",
                (review_id, owner),
            ).fetchone()
            if rev_row is None:
                raise MissionRejected("revisão ausente")
            domain_id = rev_row["domain_id"]

        _pause_review_if_requested()
        from local_security import mission_review_confirmed
        try:
            with mission_review_confirmed(owner, domain_id, session_token):
                return self._decide_locked(
                    owner, review_id, domain_id, decision, expected_revision,
                    expected_artifact_sha256, clean_reason, idempotency_key, body_hash,
                )
        except PermissionError as exc:
            raise MissionDenied("concessão de revisão revogada ou expirada") from exc

    def _decide_locked(
        self,
        owner: str,
        review_id: str,
        domain_id: str,
        decision: str,
        expected_revision: int,
        expected_artifact_sha256: str,
        reason: str | None,
        idempotency_key: str,
        body_hash: str,
    ) -> tuple[dict, bool]:
        now = _now()
        from source_admission import review_is_unverified_source
        with self.store.transaction() as connection:
            if review_is_unverified_source(connection, owner, review_id):
                raise MissionRejected("fonte em quarentena não pode ser revisada")
            existing = _find_idempotency(
                connection, owner, IDEMPOTENCY_REVIEW_DECISION, idempotency_key,
            )
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                if existing["result_json"]:
                    stored = json.loads(existing["result_json"])
                    stored["replayed"] = True
                    return stored, True
                rev = self.get_review(owner, review_id)
                if rev is not None:
                    rev["replayed"] = True
                    return rev, True
                raise MissionConflict("idempotência reutilizada com corpo diferente")

            rev_row = connection.execute(
                "SELECT * FROM mission_artifact_reviews WHERE id=? AND owner=?",
                (review_id, owner),
            ).fetchone()
            if rev_row is None:
                raise MissionRejected("revisão ausente")
            if rev_row["revision"] != expected_revision:
                raise MissionConflict("revisão divergente")
            if rev_row["artifact_sha256"] != expected_artifact_sha256:
                raise MissionConflict("versão do artefato divergente")
            if rev_row["state"] in ("approved", "rejected"):
                raise MissionConflict("revisão já encerrada")

            mission_row = connection.execute(
                "SELECT * FROM missions WHERE id=? AND owner=?",
                (rev_row["mission_id"], owner),
            ).fetchone()
            if mission_row is None:
                raise MissionRejected("missão ausente")
            if mission_row["status"] == "cancelled":
                raise MissionRejected("missão cancelada não aceita decisões de revisão")

            mission = json.loads(mission_row["document_json"])
            artifact = next((a for a in mission.get("artifacts", []) if a["id"] == rev_row["artifact_id"]), None)
            if artifact is None:
                raise MissionRejected("artefato ausente na missão")
            if _sha(artifact) != expected_artifact_sha256:
                raise MissionConflict("conteúdo do artefato diverge do esperado")

            snapshot_json = rev_row["artifact_snapshot_json"]
            try:
                snapshot = json.loads(snapshot_json)
            except (TypeError, ValueError) as exc:
                raise MissionCorrupt(review_id) from exc
            if _sha(snapshot) != expected_artifact_sha256 or snapshot.get("id") != rev_row["artifact_id"]:
                raise MissionCorrupt(review_id)

            artifact["review_state"] = decision
            artifact["reviewed_at"] = now

            event_key = f"{review_id}:{decision}:{expected_revision}"
            self._append_event(
                connection, mission, owner, "artifact_reviewed", None,
                f"Decisão de revisão: {decision}. Motivo: {reason or 'aprovado sem ressalvas'}.",
                now, stable_key=event_key,
            )
            _check_mission(mission)
            new_mission_revision = mission_row["revision"] + 1
            updated_mission = connection.execute(
                "UPDATE missions SET document_json=?, revision=?, updated_at=? WHERE id=? AND owner=? AND revision=?",
                (json.dumps(mission, ensure_ascii=False), new_mission_revision, now, mission_row["id"], owner, mission_row["revision"]),
            )
            if updated_mission.rowcount != 1:
                raise MissionConflict("missão modificada concorrentemente")

            new_review_revision = rev_row["revision"] + 1
            updated_review = connection.execute(
                """UPDATE mission_artifact_reviews
                   SET state=?, decision_reason=?, decision_actor=?, decided_at=?, revision=?, updated_at=?
                   WHERE id=? AND owner=? AND revision=?""",
                (decision, reason, owner, now, new_review_revision, now, review_id, owner, expected_revision),
            )
            if updated_review.rowcount != 1:
                raise MissionConflict("revisão modificada concorrentemente")

            dec_id = _token("rdec")
            connection.execute(
                """INSERT INTO mission_review_decisions (
                    id, review_id, mission_id, owner, artifact_id, artifact_version,
                    artifact_sha256, decision, decision_reason, actor, idempotency_key,
                    snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    dec_id, review_id, rev_row["mission_id"], owner, rev_row["artifact_id"],
                    rev_row["artifact_version"], rev_row["artifact_sha256"], decision,
                    reason, owner, idempotency_key, snapshot_json, now,
                ),
            )

            result = {
                "dataset": "api_synthetic",
                "id": review_id,
                "mission_id": rev_row["mission_id"],
                "mission_title": mission["title"],
                "mission_status": mission["status"],
                "artifact_id": rev_row["artifact_id"],
                "artifact_version": rev_row["artifact_version"],
                "artifact_sha256": rev_row["artifact_sha256"],
                "artifact": artifact,
                "domain_id": domain_id,
                "state": decision,
                "decision_reason": reason,
                "decision_actor": owner,
                "decided_at": now,
                "revision": new_review_revision,
                "created_at": rev_row["created_at"],
                "updated_at": now,
                "replayed": False,
            }

            _store_idempotency(
                connection,
                owner,
                IDEMPOTENCY_REVIEW_DECISION,
                idempotency_key,
                rev_row["mission_id"],
                body_hash,
                json.dumps(result, ensure_ascii=False),
            )

            return result, False

    def revise_review(self, owner: str, review_id: str, new_content: str, idempotency_key: str,
                      session_token: str | None = None) -> tuple[dict, bool]:
        from local_security import mission_review_confirmed, mission_write_confirmed
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT domain_id FROM mission_artifact_reviews WHERE id=? AND owner=?",
                (review_id, owner),
            ).fetchone()
        if row is None:
            raise MissionRejected("revisão ausente")
        _pause_review_if_requested()
        try:
            with mission_write_confirmed(owner, row["domain_id"], session_token):
                with mission_review_confirmed(owner, row["domain_id"], session_token):
                    return self._revise_locked(owner, review_id, new_content, idempotency_key)
        except PermissionError as exc:
            raise MissionDenied("concessão ou sessão revogada ou expirada") from exc

    def _revise_locked(self, owner: str, review_id: str, new_content: str,
                       idempotency_key: str) -> tuple[dict, bool]:
        if not new_content or not new_content.strip():
            raise MissionRejected("conteúdo revisado obrigatório")
        clean_content = new_content.strip()[:50000]

        body_hash = _sha({
            "action": "revise_review",
            "review_id": review_id,
            "new_content": clean_content,
        })
        now = _now()
        from source_admission import is_selected_source_artifact, review_is_unverified_source
        with self.store.transaction() as connection:
            if review_is_unverified_source(connection, owner, review_id):
                raise MissionRejected("fonte em quarentena não pode ser revisada")
            if is_selected_source_artifact(connection, owner, review_id):
                raise MissionRejected("conteúdo de fixture curada não pode ser alterado")
            existing = _find_idempotency(
                connection, owner, IDEMPOTENCY_REVIEW_REVISION, idempotency_key,
            )
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                if existing["result_json"]:
                    stored = json.loads(existing["result_json"])
                    stored["replayed"] = True
                    return stored, True
                raise MissionConflict("idempotência reutilizada com corpo diferente")

            rev_row = connection.execute(
                "SELECT * FROM mission_artifact_reviews WHERE id=? AND owner=?",
                (review_id, owner),
            ).fetchone()
            if rev_row is None:
                raise MissionRejected("revisão ausente")
            if rev_row["state"] != "changes_requested":
                raise MissionRejected("somente revisões com ajustes solicitados podem ser revisadas")

            mission_row = connection.execute(
                "SELECT * FROM missions WHERE id=? AND owner=?",
                (rev_row["mission_id"], owner),
            ).fetchone()
            if mission_row is None:
                raise MissionRejected("missão ausente")
            if mission_row["status"] == "cancelled":
                raise MissionRejected("missão cancelada")

            mission = json.loads(mission_row["document_json"])
            artifact = next((a for a in mission.get("artifacts", []) if a["id"] == rev_row["artifact_id"]), None)
            if artifact is None:
                raise MissionRejected("artefato ausente na missão")

            artifact["content"] = clean_content
            artifact["review_state"] = "pending"
            artifact["reviewed_at"] = None
            artifact["created_at"] = now
            new_sha = _sha(artifact)
            new_version = rev_row["artifact_version"] + 1
            new_review_id = f"rev_{artifact['id']}_{new_version}"

            connection.execute(
                """INSERT INTO mission_artifact_reviews (
                    id, mission_id, owner, artifact_id, artifact_version,
                    artifact_sha256, domain_id, state, decision_reason,
                decision_actor, decided_at, revision, created_at, updated_at,
                artifact_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, 1, ?, ?, ?)""",
                (
                    new_review_id, rev_row["mission_id"], owner, artifact["id"],
                    new_version, new_sha, rev_row["domain_id"], now, now,
                    json.dumps(artifact, ensure_ascii=False),
                ),
            )

            self._append_event(
                connection, mission, owner, "artifact_created", None,
                f"Versão {new_version} do artefato atualizada após ajustes.",
                now, stable_key=f"{new_review_id}:revised",
            )
            _check_mission(mission)
            new_mission_revision = mission_row["revision"] + 1
            connection.execute(
                "UPDATE missions SET document_json=?, revision=?, updated_at=? WHERE id=? AND owner=? AND revision=?",
                (json.dumps(mission, ensure_ascii=False), new_mission_revision, now, mission_row["id"], owner, mission_row["revision"]),
            )

            result = {
                "dataset": "api_synthetic",
                "id": new_review_id,
                "mission_id": rev_row["mission_id"],
                "mission_title": mission["title"],
                "mission_status": mission["status"],
                "artifact_id": artifact["id"],
                "artifact_version": new_version,
                "artifact_sha256": new_sha,
                "artifact": artifact,
                "domain_id": rev_row["domain_id"],
                "state": "pending",
                "decision_reason": None,
                "decision_actor": None,
                "decided_at": None,
                "revision": 1,
                "created_at": now,
                "updated_at": now,
                "replayed": False,
            }

            _store_idempotency(
                connection,
                owner,
                IDEMPOTENCY_REVIEW_REVISION,
                idempotency_key,
                rev_row["mission_id"],
                body_hash,
                json.dumps(result, ensure_ascii=False),
            )

            return result, False
