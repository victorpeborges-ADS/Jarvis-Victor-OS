"""Transactional synthetic mission persistence inside the existing SQLite store."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from mission_contracts import validate_contract
from synthetic_skill import capture_and_classify

MAX_TASKS = 20
MAX_TITLE = 240
PAGE_LIMIT = 20


class MissionConflict(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


class MissionRejected(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


class MissionCorrupt(Exception):
    def __init__(self, mission_id: str) -> None:
        self.mission_id = mission_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    _acyclic(list(document["tasks"]))
    if document["status"] == "done" and any(task["status"] != "done" for task in document["tasks"]):
        raise MissionRejected("missão concluída sem etapas concluídas")


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
            existing = connection.execute(
                "SELECT mission_id, body_sha256 FROM mission_idempotency WHERE owner=? AND idempotency_key=?",
                (owner, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                row = connection.execute("SELECT * FROM missions WHERE id=? AND owner=?", (existing["mission_id"], owner)).fetchone()
                if row is None:
                    raise MissionRejected("registro de idempotência órfão")
                return _record_from_row(row), True
            record = new_mission(title, domain_id, owner)
            self._insert_record(connection, record, owner, idempotency_key, body_hash)
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

    def list_page(self, owner: str, domain_id: str | None, limit: int, cursor: str | None) -> dict:
        limit = min(max(limit, 1), PAGE_LIMIT)
        clauses = ["owner=?"]
        params: list[Any] = [owner]
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

    def transition(self, owner: str, mission_id: str, action: str, expected_revision: int, idempotency_key: str) -> dict:
        if action in {"run_next", "resume"}:
            from mission_engine import MissionEngine
            return MissionEngine(self).run(owner, mission_id, action, expected_revision, idempotency_key)
        body_hash = _sha({"action": action, "mission_id": mission_id, "expected_revision": expected_revision})
        with self.store.transaction() as connection:
            existing = connection.execute(
                "SELECT mission_id, body_sha256 FROM mission_idempotency WHERE owner=? AND idempotency_key=?",
                (owner, idempotency_key),
            ).fetchone()
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
            connection.execute(
                "INSERT INTO mission_idempotency(owner, idempotency_key, mission_id, body_sha256) VALUES (?, ?, ?, ?)",
                (owner, idempotency_key, mission_id, body_hash),
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
                "UPDATE mission_executions SET phase='interrupted', committed_at=? WHERE mission_id=? AND owner=? AND phase IN ('open', 'interrupted')",
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

    def _insert_record(self, connection, record: dict, owner: str, idempotency_key: str, body_hash: str) -> None:
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
        connection.execute(
            "INSERT INTO mission_idempotency(owner, idempotency_key, mission_id, body_sha256) VALUES (?, ?, ?, ?)",
            (owner, idempotency_key, mission["id"], body_hash),
        )

    def import_valid(self, owner: str, documents: list[dict], idempotency_key: str) -> dict:
        accepted = []
        quarantined = []
        for index, document in enumerate(documents):
            try:
                _check_mission(document)
                if document.get("domain_id") is None:
                    raise MissionRejected("domínio ausente")
            except MissionRejected as exc:
                quarantined.append({"index": index, "reason": exc.detail})
        if quarantined and len(quarantined) == len(documents):
            return {"dataset": "api_synthetic", "accepted": [], "quarantined": quarantined}
        body_hash = _sha({"scope": "mission_import", "owner": owner, "documents": documents})
        with self.store.transaction() as connection:
            existing = connection.execute(
                "SELECT mission_id, body_sha256, result_json FROM mission_idempotency WHERE owner=? AND idempotency_key=?",
                (owner, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                if existing["result_json"]:
                    stored = json.loads(existing["result_json"])
                    stored["replayed"] = True
                    return stored
                return {"dataset": "api_synthetic", "accepted": [], "quarantined": quarantined, "replayed": True, "legacy": True}
            for index, document in enumerate(documents):
                if any(item["index"] == index for item in quarantined):
                    continue
                found = connection.execute(
                    "SELECT id FROM missions WHERE id=? AND owner=?",
                    (document["id"], owner),
                ).fetchone()
                if found is not None:
                    continue
                record = {
                    "dataset": "api_synthetic",
                    "owner": owner,
                    "revision": 1,
                    "access_class": "synthetic_local",
                    "mission": document,
                }
                self._insert_record(connection, record, owner, f"{idempotency_key}:{document['id']}", _sha(document))
                accepted.append(document["id"])
            result = {"dataset": "api_synthetic", "accepted": accepted, "quarantined": quarantined, "replayed": False}
            connection.execute(
                "INSERT INTO mission_idempotency(owner, idempotency_key, mission_id, body_sha256, result_json) VALUES (?, ?, ?, ?, ?)",
                (owner, idempotency_key, accepted[0] if accepted else "mission_import_empty", body_hash, json.dumps(result, ensure_ascii=False)),
            )
        return result
