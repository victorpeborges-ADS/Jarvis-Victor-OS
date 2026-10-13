"""Closed, deterministic workflow catalog and durable local executor."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Type

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from typing_extensions import Annotated, Literal

from memory_store import SQLiteMemoryStore

APPROVAL_TTL = timedelta(seconds=60)
_SESSION_BINDING_KEY = secrets.token_bytes(32)
_IDEMPOTENCY = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
_SECRET_MARKER = re.compile(r"(?i)(?:bearer\s+[a-z0-9._-]{8,}|(?:token|secret|password|passphrase|authorization)\s*[:=])")
_EVENTS = {
    "created", "paused", "resumed", "cancelled", "approval_issued",
    "execution_opened", "execution_interrupted", "execution_succeeded", "execution_failed",
}


class WorkflowError(Exception):
    """An allowlisted, non-sensitive workflow failure code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TransientFailure(Exception):
    """Only deterministic local handlers may raise this retry signal."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


ShortText = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"[^\x00-\x1f\x7f]+")]
BodyText = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"[^\x00-\x1f\x7f]+")]


class DraftNoteArgs(StrictModel):
    title: ShortText
    body: BodyText


class SimulatedPayload(StrictModel):
    subject: Annotated[str, StringConstraints(min_length=1, max_length=30, pattern=r"[^\x00-\x1f\x7f]+")]
    body: BodyText


class SimulateActionArgs(StrictModel):
    service: Literal["synthetic-mail"]
    account: Literal["operator@example.test"]
    target: Literal["synthetic-outbox"]
    payload: SimulatedPayload


class EmptyArgs(StrictModel):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    retryable: tuple[str, ...]


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    schema: Type[BaseModel]
    permission: str
    risk: str
    timeout_ms: int
    limit: int
    retry: RetryPolicy
    expected_effect: str
    enabled: bool
    approval_required: bool


TOOLS: dict[str, ToolSpec] = {
    "draft_note": ToolSpec(
        "draft_note", DraftNoteArgs, "session:active", "low", 250, 1,
        RetryPolicy(1, ()), "rascunho local persistido", True, False,
    ),
    "simulate_action": ToolSpec(
        "simulate_action", SimulateActionArgs, "mission:review", "medium", 500, 1,
        RetryPolicy(2, ("transient_local",)), "simulação local sem envio", True, True,
    ),
    "send_message": ToolSpec(
        "send_message", EmptyArgs, "message:send", "high", 500, 1,
        RetryPolicy(1, ()), "envio externo", False, True,
    ),
    "pay": ToolSpec(
        "pay", EmptyArgs, "payment:create", "critical", 500, 1,
        RetryPolicy(1, ()), "pagamento externo", False, True,
    ),
    "delete_record": ToolSpec(
        "delete_record", EmptyArgs, "record:delete", "critical", 500, 1,
        RetryPolicy(1, ()), "exclusão externa", False, True,
    ),
    "invite_member": ToolSpec(
        "invite_member", EmptyArgs, "invite:create", "high", 500, 1,
        RetryPolicy(1, ()), "convite externo", False, True,
    ),
}


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def session_binding(session_token: str) -> str:
    """Opaque process-bound reference; raw G5 tokens are never persisted."""
    return hmac.new(_SESSION_BINDING_KEY, session_token.encode("utf-8"), hashlib.sha256).hexdigest()


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowError("clock_rejected")
    return value.astimezone(timezone.utc).isoformat()


def _owner_time(owner: str, now: datetime) -> str:
    if owner != "owner":
        raise WorkflowError("owner_rejected")
    return _stamp(now)


def _validated_arguments(tool_id: str, raw: object) -> tuple[ToolSpec, dict]:
    if not isinstance(tool_id, str) or tool_id not in TOOLS or not isinstance(raw, dict):
        raise WorkflowError("recommendation_rejected")
    spec = TOOLS[tool_id]
    if not spec.enabled:
        raise WorkflowError("tool_blocked")
    try:
        parsed = spec.schema.model_validate(raw)
        arguments = parsed.model_dump(mode="json")
        serialized = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValidationError, TypeError, ValueError):
        raise WorkflowError("schema_rejected") from None
    if len(serialized.encode("utf-8")) > 700:
        raise WorkflowError("limit_exceeded")
    if _SECRET_MARKER.search(serialized):
        raise WorkflowError("schema_rejected")
    return spec, arguments


def accept_recommendation(raw: object) -> tuple[ToolSpec, dict]:
    """The only model-facing contract: a known tool id and typed arguments."""
    if not isinstance(raw, dict) or set(raw) != {"tool_id", "arguments"}:
        raise WorkflowError("recommendation_rejected")
    return _validated_arguments(raw["tool_id"], raw["arguments"])


def _preview(spec: ToolSpec, arguments: dict) -> dict:
    if spec.tool_id != "simulate_action":
        return {}
    return {
        "service": "E-mail sintético (simulação local)",
        "account": arguments["account"],
        "target": arguments["target"],
        "payload": arguments["payload"],
        "consequence": "Nenhuma mensagem será enviada; somente um resultado local de simulação será registrado.",
        "data_sent": [],
        "risk": spec.risk,
    }


class WorkflowExecutor:
    def __init__(self, store: SQLiteMemoryStore) -> None:
        self.store = store

    def submit(self, owner: str, recommendation: object, idempotency_key: str, now: datetime) -> dict:
        stamp = _owner_time(owner, now)
        if not isinstance(idempotency_key, str) or _IDEMPOTENCY.fullmatch(idempotency_key) is None:
            raise WorkflowError("idempotency_key_rejected")
        spec, arguments = accept_recommendation(recommendation)
        arguments_json = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        digest = canonical_sha({"tool_id": spec.tool_id, "arguments": arguments})
        preview = _preview(spec, arguments)
        state = "awaiting_approval" if spec.approval_required else "proposed"
        with self.store.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM workflow_tasks WHERE owner=? AND idempotency_key=?", (owner, idempotency_key)
            ).fetchone()
            if existing is not None:
                if existing["arguments_sha"] != digest:
                    raise WorkflowError("idempotency_conflict")
                return self._public(connection, existing["id"])
            task_id = secrets.token_hex(16)
            connection.execute(
                """INSERT INTO workflow_tasks
                   (id, owner, tool_id, arguments_json, arguments_sha, state, idempotency_key,
                    preview_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, owner, spec.tool_id, arguments_json, digest, state, idempotency_key,
                 json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if preview else None,
                 stamp, stamp),
            )
            self._log(connection, task_id, stamp, "created")
            return self._public(connection, task_id)

    def list_tasks(self, owner: str, now: datetime, limit: int = 20) -> list[dict]:
        _owner_time(owner, now)
        if not 1 <= limit <= 20:
            raise WorkflowError("limit_exceeded")
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT id FROM workflow_tasks WHERE owner=? ORDER BY updated_at DESC, id LIMIT ?", (owner, limit)
            ).fetchall()
            summaries = []
            for row in rows:
                task = self._public(connection, row["id"], include_result=False)
                summaries.append({key: task[key] for key in (
                    "task_id", "tool_id", "state", "arguments_sha", "created_at", "updated_at", "risk", "expected_effect"
                )})
            return summaries

    def detail(self, owner: str, task_id: str, now: datetime) -> dict:
        _owner_time(owner, now)
        with self.store.transaction() as connection:
            self._require(connection, owner, task_id)
            return self._public(connection, task_id)

    def approve(
        self, owner: str, task_id: str, expected_sha: str,
        session_ref: str, grant_id: str, now: datetime,
    ) -> dict:
        stamp = _owner_time(owner, now)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", grant_id):
            raise WorkflowError("approval_rejected")
        with self.store.transaction() as connection:
            task = self._require(connection, owner, task_id)
            self._stored_arguments(task)
            spec = TOOLS.get(task["tool_id"])
            if spec is None or not spec.enabled or not spec.approval_required:
                raise WorkflowError("approval_not_required")
            if task["state"] not in {"awaiting_approval", "interrupted"}:
                raise WorkflowError("state_rejected")
            if task["arguments_sha"] != expected_sha:
                raise WorkflowError("parameters_changed")
            existing = connection.execute("SELECT * FROM workflow_approvals WHERE task_id=?", (task_id,)).fetchone()
            if existing is not None and existing["used_at"] is None and existing["expires_at"] > stamp:
                if existing["arguments_sha"] == expected_sha and existing["session_binding"] == session_ref and existing["grant_id"] == grant_id:
                    return {"expires_at": existing["expires_at"], "arguments_sha": expected_sha}
            expiry = _stamp(now + APPROVAL_TTL)
            approval_id = secrets.token_hex(16)
            connection.execute(
                """INSERT INTO workflow_approvals
                   (id, task_id, arguments_sha, session_binding, grant_id, expires_at, used_at)
                   VALUES (?, ?, ?, ?, ?, ?, NULL)
                   ON CONFLICT(task_id) DO UPDATE SET id=excluded.id, arguments_sha=excluded.arguments_sha,
                     session_binding=excluded.session_binding, grant_id=excluded.grant_id,
                     expires_at=excluded.expires_at, used_at=NULL""",
                (approval_id, task_id, expected_sha, session_ref, grant_id, expiry),
            )
            connection.execute("UPDATE workflow_tasks SET updated_at=? WHERE id=?", (stamp, task_id))
            self._log(connection, task_id, stamp, "approval_issued")
            return {"expires_at": expiry, "arguments_sha": expected_sha}

    def approval_grant_id(self, owner: str, task_id: str, now: datetime) -> str:
        _owner_time(owner, now)
        with self.store.transaction() as connection:
            self._require(connection, owner, task_id)
            row = connection.execute("SELECT grant_id FROM workflow_approvals WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise WorkflowError("approval_required")
            return row["grant_id"]

    def execute(
        self, owner: str, task_id: str, idempotency_key: str,
        session_ref: str, grant_id: str | None, now: datetime,
    ) -> dict:
        stamp = _owner_time(owner, now)
        if not isinstance(idempotency_key, str) or _IDEMPOTENCY.fullmatch(idempotency_key) is None:
            raise WorkflowError("idempotency_key_rejected")
        with self.store.transaction() as connection:
            task = self._require(connection, owner, task_id)
            if task["idempotency_key"] != idempotency_key:
                raise WorkflowError("idempotency_conflict")
            spec = TOOLS.get(task["tool_id"])
            if spec is None or not spec.enabled:
                raise WorkflowError("tool_blocked")
            arguments = self._stored_arguments(task)
            result_row = connection.execute("SELECT * FROM workflow_results WHERE task_id=?", (task_id,)).fetchone()
            approval = connection.execute("SELECT * FROM workflow_approvals WHERE task_id=?", (task_id,)).fetchone()
            if result_row is not None:
                if spec.approval_required and not self._approval_matches(approval, task, session_ref, grant_id, require_unused=False):
                    raise WorkflowError("grant_rejected")
                output = json.loads(result_row["output_json"])
                expected = canonical_sha({"effect": result_row["effect"], "tool_id": task["tool_id"], "output": output})
                if not hmac.compare_digest(expected, result_row["result_sha"]):
                    raise WorkflowError("result_corrupt")
                return {**self._public(connection, task_id), "result": output,
                        "effect": result_row["effect"], "result_sha": result_row["result_sha"],
                        "attempts": result_row["attempts"], "replayed": True}
            if spec.approval_required:
                if task["state"] not in {"awaiting_approval", "interrupted"}:
                    raise WorkflowError("state_rejected")
                if approval is not None and approval["expires_at"] <= stamp:
                    raise WorkflowError("approval_expired")
                if not self._approval_matches(approval, task, session_ref, grant_id, require_unused=True):
                    raise WorkflowError("approval_rejected")
                changed = connection.execute(
                    "UPDATE workflow_approvals SET used_at=? WHERE task_id=? AND used_at IS NULL AND expires_at>?",
                    (stamp, task_id, stamp),
                ).rowcount
                if changed != 1:
                    raise WorkflowError("approval_replayed")
            elif task["state"] != "proposed":
                raise WorkflowError("state_rejected")
            connection.execute("UPDATE workflow_tasks SET state='running', updated_at=? WHERE id=?", (stamp, task_id))
            connection.execute(
                """INSERT INTO workflow_executions(id, task_id, phase, attempts, created_at)
                   VALUES (?, ?, 'open', 0, ?)
                   ON CONFLICT(task_id) DO UPDATE SET phase='open', attempts=0, created_at=excluded.created_at""",
                (secrets.token_hex(16), task_id, stamp),
            )
            self._log(connection, task_id, stamp, "execution_opened")

        try:
            output, attempts = self._run_tool(spec, arguments)
        except WorkflowError:
            self._mark_failed(owner, task_id)
            raise
        effect = spec.expected_effect
        result_sha = canonical_sha({"effect": effect, "tool_id": spec.tool_id, "output": output})
        with self.store.transaction() as connection:
            current = self._require(connection, owner, task_id)
            if current["state"] != "running":
                raise WorkflowError("state_rejected")
            connection.execute(
                "INSERT INTO workflow_results(task_id, effect, output_json, result_sha, attempts) VALUES (?, ?, ?, ?, ?)",
                (task_id, effect, json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")), result_sha, attempts),
            )
            connection.execute("UPDATE workflow_executions SET phase='committed', attempts=? WHERE task_id=?", (attempts, task_id))
            connection.execute("UPDATE workflow_tasks SET state='succeeded', updated_at=? WHERE id=?", (_stamp(datetime.now(timezone.utc)), task_id))
            self._log(connection, task_id, _stamp(datetime.now(timezone.utc)), "execution_succeeded")
            return {**self._public(connection, task_id), "result": output, "effect": effect,
                    "result_sha": result_sha, "attempts": attempts, "replayed": False}

    def pause(self, owner: str, task_id: str, now: datetime) -> dict:
        return self._transition(owner, task_id, now, {"proposed", "awaiting_approval"}, "paused", True, "paused")

    def resume(self, owner: str, task_id: str, now: datetime) -> dict:
        stamp = _owner_time(owner, now)
        with self.store.transaction() as connection:
            task = self._require(connection, owner, task_id)
            if task["state"] == "interrupted" and task["tool_id"] == "simulate_action":
                raise WorkflowError("approval_required")
            if task["state"] == "interrupted" and task["tool_id"] == "draft_note":
                next_state = "proposed"
            elif task["state"] == "paused" and task["resume_state"] in {"proposed", "awaiting_approval"}:
                next_state = task["resume_state"]
            else:
                raise WorkflowError("state_rejected")
            connection.execute("UPDATE workflow_tasks SET state=?, resume_state=NULL, updated_at=? WHERE id=?", (next_state, stamp, task_id))
            self._log(connection, task_id, stamp, "resumed")
            return self._public(connection, task_id)

    def cancel(self, owner: str, task_id: str, now: datetime) -> dict:
        return self._transition(owner, task_id, now, {"proposed", "awaiting_approval", "paused", "running", "interrupted", "failed"}, "cancelled", False, "cancelled")

    def recover(self, now: datetime) -> int:
        stamp = _stamp(now)
        with self.store.transaction() as connection:
            rows = connection.execute("SELECT task_id FROM workflow_executions WHERE phase='open'").fetchall()
            for row in rows:
                task_id = row["task_id"]
                connection.execute("UPDATE workflow_executions SET phase='interrupted' WHERE task_id=? AND phase='open'", (task_id,))
                connection.execute("UPDATE workflow_tasks SET state='interrupted', updated_at=? WHERE id=? AND state='running'", (stamp, task_id))
                self._log(connection, task_id, stamp, "execution_interrupted")
            return len(rows)

    def _run_tool(self, spec: ToolSpec, arguments: dict) -> tuple[dict, int]:
        last_error: Exception | None = None
        for attempt in range(1, spec.retry.max_attempts + 1):
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-workflow-local")
            future = pool.submit(self._execute_once, spec, arguments)
            try:
                output = future.result(timeout=spec.timeout_ms / 1000)
                pool.shutdown(wait=True, cancel_futures=True)
                return output, attempt
            except FutureTimeout:
                future.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                raise WorkflowError("timeout") from None
            except TransientFailure as exc:
                last_error = exc
                pool.shutdown(wait=True, cancel_futures=True)
                if attempt >= spec.retry.max_attempts or "transient_local" not in spec.retry.retryable:
                    break
            except WorkflowError:
                pool.shutdown(wait=True, cancel_futures=True)
                raise
            except Exception:
                pool.shutdown(wait=True, cancel_futures=True)
                raise WorkflowError("operation_failed") from None
        raise WorkflowError("retry_exhausted") from last_error

    @staticmethod
    def _execute_once(spec: ToolSpec, arguments: dict) -> dict:
        if spec.tool_id == "draft_note":
            return {"title": arguments["title"], "body": arguments["body"], "stored_in_task": True}
        if spec.tool_id == "simulate_action":
            return {"simulated": True, "sent": False, "data_sent": [], "target": arguments["target"]}
        raise WorkflowError("tool_blocked")

    def _mark_failed(self, owner: str, task_id: str) -> None:
        stamp = _stamp(datetime.now(timezone.utc))
        with self.store.transaction() as connection:
            task = self._require(connection, owner, task_id)
            if task["state"] == "running":
                connection.execute("UPDATE workflow_tasks SET state='failed', updated_at=? WHERE id=?", (stamp, task_id))
                connection.execute("UPDATE workflow_executions SET phase='interrupted' WHERE task_id=? AND phase='open'", (task_id,))
                self._log(connection, task_id, stamp, "execution_failed")

    def _transition(self, owner: str, task_id: str, now: datetime, allowed: set[str], state: str, keep_resume: bool, event: str) -> dict:
        stamp = _owner_time(owner, now)
        with self.store.transaction() as connection:
            task = self._require(connection, owner, task_id)
            if task["state"] not in allowed:
                raise WorkflowError("state_rejected")
            resume_state = task["state"] if keep_resume else None
            connection.execute("UPDATE workflow_tasks SET state=?, resume_state=?, updated_at=? WHERE id=?", (state, resume_state, stamp, task_id))
            if state == "paused" and task["state"] == "awaiting_approval":
                connection.execute("UPDATE workflow_approvals SET used_at=? WHERE task_id=? AND used_at IS NULL", (stamp, task_id))
            self._log(connection, task_id, stamp, event)
            return self._public(connection, task_id)

    def _approval_matches(self, approval, task, session_ref: str, grant_id: str | None, *, require_unused: bool) -> bool:
        if approval is None or grant_id is None:
            return False
        if approval["arguments_sha"] != task["arguments_sha"] or approval["session_binding"] != session_ref or approval["grant_id"] != grant_id:
            return False
        if require_unused and approval["used_at"] is not None:
            return False
        return True

    def _require(self, connection, owner: str, task_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", task_id or ""):
            raise WorkflowError("task_not_found")
        row = connection.execute("SELECT * FROM workflow_tasks WHERE id=? AND owner=?", (task_id, owner)).fetchone()
        if row is None:
            raise WorkflowError("task_not_found")
        return row

    def _public(self, connection, task_id: str, *, include_result: bool = True) -> dict:
        task = connection.execute("SELECT * FROM workflow_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise WorkflowError("task_not_found")
        spec = TOOLS.get(task["tool_id"])
        if spec is None:
            raise WorkflowError("task_corrupt")
        self._stored_arguments(task)
        result = {
            "task_id": task["id"], "tool_id": task["tool_id"], "state": task["state"],
            "arguments_sha": task["arguments_sha"], "idempotency_key": task["idempotency_key"],
            "created_at": task["created_at"], "updated_at": task["updated_at"],
            "permission": spec.permission, "risk": spec.risk, "timeout_ms": spec.timeout_ms,
            "limit": spec.limit, "retry": {"max_attempts": spec.retry.max_attempts, "retryable": list(spec.retry.retryable)},
            "expected_effect": spec.expected_effect, "enabled": spec.enabled,
        }
        if task["preview_json"]:
            result["preview"] = json.loads(task["preview_json"])
        if include_result:
            row = connection.execute("SELECT * FROM workflow_results WHERE task_id=?", (task_id,)).fetchone()
            if row is not None:
                try:
                    output = json.loads(row["output_json"])
                except (ValueError, TypeError):
                    raise WorkflowError("result_corrupt") from None
                expected = canonical_sha({"effect": row["effect"], "tool_id": task["tool_id"], "output": output})
                if not hmac.compare_digest(expected, row["result_sha"]):
                    raise WorkflowError("result_corrupt")
                result["result"] = output
                result["result_sha"] = row["result_sha"]
                result["effect"] = row["effect"]
                result["attempts"] = row["attempts"]
        return result

    @staticmethod
    def _stored_arguments(task) -> dict:
        try:
            raw = json.loads(task["arguments_json"])
            spec, arguments = _validated_arguments(task["tool_id"], raw)
            digest = canonical_sha({"tool_id": spec.tool_id, "arguments": arguments})
        except (ValueError, TypeError, WorkflowError):
            raise WorkflowError("task_corrupt") from None
        if not hmac.compare_digest(digest, task["arguments_sha"]):
            raise WorkflowError("task_corrupt")
        return arguments

    @staticmethod
    def _log(connection, task_id: str, stamp: str, event: str) -> None:
        if event not in _EVENTS:
            raise WorkflowError("log_event_rejected")
        connection.execute("INSERT INTO workflow_log(task_id, at, event) VALUES (?, ?, ?)", (task_id, stamp, event))
