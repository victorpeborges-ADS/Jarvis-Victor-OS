"""Two-phase supervised mission steps for one local process."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from synthetic_skill import capture_and_classify

MAX_ATTEMPTS = 3


def available_actions(status: str) -> list[str]:
    table = {
        "planned": ["run_next", "cancel"],
        "running": ["run_next", "cancel", "fail"],
        "blocked": ["run_next", "cancel"],
        "interrupted": ["resume", "cancel", "fail"],
        "failed": ["retry", "cancel"],
    }
    return table.get(status, [])


def recover_interrupted(store) -> int:
    """Fail closed: an open execution did not commit its artifact."""
    from mission_repository import MissionCorrupt, _now, _record_from_row

    changed = 0
    with store.transaction() as connection:
        rows = connection.execute(
            "SELECT id, mission_id, owner FROM mission_executions WHERE phase='open'"
        ).fetchall()
        now = _now()
        for row in rows:
            connection.execute(
                "UPDATE mission_executions SET phase='interrupted', committed_at=? WHERE id=? AND phase='open'",
                (now, row["id"]),
            )
            mission_row = connection.execute(
                "SELECT * FROM missions WHERE id=? AND owner=?",
                (row["mission_id"], row["owner"]),
            ).fetchone()
            if mission_row is None:
                continue
            try:
                record = _record_from_row(mission_row)
            except MissionCorrupt:
                continue
            mission = record["mission"]
            if mission["status"] in {"done", "cancelled"}:
                continue
            mission["status"] = "interrupted"
            mission["updated_at"] = now
            connection.execute(
                "UPDATE missions SET status=?, revision=revision+1, document_json=?, updated_at=? WHERE id=? AND owner=?",
                (mission["status"], json.dumps(mission, ensure_ascii=False), now, mission["id"], row["owner"]),
            )
            changed += 1
    return changed


def _pause_if_requested() -> None:
    raw = os.environ.get("JARVIS_TEST_PAUSE_FILE")
    if not raw:
        return
    path = Path(raw)
    path.write_text("open", encoding="utf-8")
    deadline = time.time() + 30
    while time.time() < deadline:
        if path.read_text(encoding="utf-8") == "go":
            return
        time.sleep(0.05)


def _digest(title: str, task_id: str) -> str:
    return hashlib.sha256(f"{task_id}:{title}".encode("utf-8")).hexdigest()


def _produce(mission: dict, task: dict, now: str) -> tuple[dict, dict | None]:
    digest = _digest(mission["title"], task["id"])
    if task["id"] == "task_capture":
        artifact, knowledge = capture_and_classify(mission["title"], mission["domain_id"], now, mission["id"])
        artifact["skill_id"] = "capture-and-classify"
        artifact["input_digest"] = digest
        return artifact, knowledge
    if task["id"] == "task_context":
        content = "Minimização determinística no servidor. O filtro do navegador não autoriza esta etapa."
        skill = "build-context"
    elif task["id"] == "task_report":
        content = "Rascunho determinístico aguardando revisão humana. Nenhuma aprovação foi marcada."
        skill = "draft-evidenced-report"
    else:
        content = f"Etapa determinística {task['id']} sem efeito externo."
        skill = "local-step"
    artifact = {
        "id": f"artifact_{task['id']}_{digest[:16]}",
        "kind": "context_bundle" if task["id"] == "task_context" else "report" if task["id"] == "task_report" else "evidence",
        "title": task["title"][:240],
        "content": content,
        "skill_version": "1.0.0",
        "skill_id": skill,
        "input_digest": digest,
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
    return artifact, None


class MissionEngine:
    def __init__(self, repository) -> None:
        self.repository = repository

    def run(self, owner: str, mission_id: str, action: str, expected_revision: int, idempotency_key: str) -> dict:
        from mission_repository import MissionConflict, MissionRejected, _now, _record_from_row, _sha

        body_hash = _sha({"action": action, "mission_id": mission_id, "expected_revision": expected_revision})
        store = self.repository.store
        with store.transaction() as connection:
            existing = connection.execute(
                "SELECT mission_id, body_sha256 FROM mission_idempotency WHERE owner=? AND idempotency_key=?",
                (owner, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["body_sha256"] != body_hash or existing["mission_id"] != mission_id:
                    raise MissionConflict("idempotência reutilizada com corpo diferente")
                row = connection.execute("SELECT * FROM missions WHERE id=? AND owner=?", (mission_id, owner)).fetchone()
                return _record_from_row(row)
            row = connection.execute("SELECT * FROM missions WHERE id=? AND owner=?", (mission_id, owner)).fetchone()
            if row is None:
                raise MissionRejected("registro ausente")
            if row["revision"] != expected_revision:
                raise MissionConflict("revisão divergente")
            record = _record_from_row(row)
            mission = record["mission"]
            if action == "resume":
                if mission["status"] != "interrupted":
                    raise MissionRejected("retomada exige missão interrompida")
                execution = connection.execute(
                    "SELECT * FROM mission_executions WHERE mission_id=? AND owner=? AND phase='interrupted' ORDER BY created_at DESC LIMIT 1",
                    (mission_id, owner),
                ).fetchone()
                if execution is None:
                    raise MissionRejected("não há execução interrompida")
                task = next(item for item in mission["tasks"] if item["id"] == execution["task_id"])
                execution_id = execution["id"]
            else:
                if mission["status"] in {"cancelled", "failed", "done", "interrupted"}:
                    raise MissionRejected("execução não se aplica a este estado")
                task = next((
                    item for item in mission["tasks"]
                    if item["status"] in {"planned", "blocked"}
                    and all(any(dep["id"] == dependency and dep["status"] == "done" for dep in mission["tasks"]) for dependency in item["depends_on"])
                ), None)
                if task is None:
                    raise MissionRejected("nenhuma etapa executável")
                if task["attempt"] > MAX_ATTEMPTS:
                    raise MissionRejected("limite de tentativas")
                execution_id = f"exec_{mission_id[-12:]}_{task['id']}_{task['attempt']}"
                connection.execute(
                    "INSERT INTO mission_executions(id, mission_id, owner, task_id, phase, attempt, skill_id, skill_version, input_digest, revision_at_start, created_at) VALUES (?, ?, ?, ?, 'open', ?, ?, '1.0.0', ?, ?, ?)",
                    (execution_id, mission_id, owner, task["id"], task["attempt"], "capture-and-classify" if task["id"] == "task_capture" else "local-step", _digest(mission["title"], task["id"]), expected_revision, _now()),
                )
                mission["status"] = "running"
                task["status"] = "running"
                task["updated_at"] = _now()
                mission["updated_at"] = task["updated_at"]
                connection.execute(
                    "UPDATE missions SET status=?, document_json=?, updated_at=? WHERE id=? AND owner=? AND revision=?",
                    ("running", json.dumps(mission, ensure_ascii=False), mission["updated_at"], mission_id, owner, expected_revision),
                )
        _pause_if_requested()
        now = _now()
        artifact, knowledge = _produce(mission, task, now)
        with store.transaction() as connection:
            current = connection.execute(
                "SELECT phase FROM mission_executions WHERE id=?",
                (execution_id,),
            ).fetchone()
            if current is None or current["phase"] not in {"open", "interrupted"}:
                raise MissionConflict("execução já encerrada")
            fresh = connection.execute("SELECT * FROM missions WHERE id=? AND owner=?", (mission_id, owner)).fetchone()
            record = _record_from_row(fresh)
            mission = record["mission"]
            task = next(item for item in mission["tasks"] if item["id"] == task["id"])
            if not any(item["id"] == artifact["id"] for item in mission["artifacts"]):
                mission["artifacts"].append(artifact)
            if knowledge is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO mission_knowledge(id, owner, mission_id, domain_id, state, content, skill_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (knowledge["id"], owner, mission_id, knowledge["domain_id"], knowledge["state"], knowledge["content"], knowledge["skill_version"], now),
                )
            task["status"] = "done"
            task["updated_at"] = now
            self.repository._append_event(connection, mission, owner, "task_completed", task["id"], f"Etapa determinística confirmada: {task['title']}.", now, stable_key=f"{execution_id}:completed")
            self.repository._append_event(connection, mission, owner, "artifact_created", task["id"], "Artefato draft confirmado na mesma transação.", now, stable_key=f"{execution_id}:artifact")
            mission["status"] = "done" if all(item["status"] == "done" for item in mission["tasks"]) else "running"
            mission["updated_at"] = now
            from mission_repository import _check_mission
            _check_mission(mission)
            if mission["status"] == "done" and any(item.get("review_state") not in {None, "draft", "not_required", "awaiting_approval"} for item in mission["artifacts"]):
                raise MissionRejected("conclusão não pode aprovar artefato")
            revision = fresh["revision"] + 1
            connection.execute(
                "UPDATE missions SET status=?, revision=?, document_json=?, updated_at=? WHERE id=? AND owner=?",
                (mission["status"], revision, json.dumps(mission, ensure_ascii=False), now, mission_id, owner),
            )
            connection.execute(
                "UPDATE mission_executions SET phase='committed', committed_at=? WHERE id=?",
                (now, execution_id),
            )
            connection.execute(
                "INSERT OR IGNORE INTO mission_idempotency(owner, idempotency_key, mission_id, body_sha256) VALUES (?, ?, ?, ?)",
                (owner, idempotency_key, mission_id, body_hash),
            )
            fresh = connection.execute("SELECT * FROM missions WHERE id=? AND owner=?", (mission_id, owner)).fetchone()
            return _record_from_row(fresh)
