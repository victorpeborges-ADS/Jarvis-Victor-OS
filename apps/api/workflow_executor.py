"""Closed, deterministic workflow catalog and durable local executor."""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import re
import secrets
import threading
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


class EffectUncertain(Exception):
    """The fake ledger may already contain the effect and the ack was lost."""


_EFFECT_DISPATCH: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "jarvis_effect_dispatch", default=None
)
_CONNECTOR_MODES = frozenset({"succeed", "fail", "uncertain", "stall_before", "stall_after", "hold_after"})


class FakeSyntheticConnector:
    """Records one synthetic effect in SQLite. It does not open a socket or a process."""

    def __init__(self) -> None:
        self.mode = "succeed"
        self.calls = 0
        self.entered = threading.Event()
        self.gate = threading.Event()

    def apply(self, store: SQLiteMemoryStore, *, idempotency_key: str, binding_sha: str, stamp: str) -> str:
        if self.mode not in _CONNECTOR_MODES:
            raise WorkflowError("tool_blocked")
        self.calls += 1
        if self.mode == "fail":
            raise WorkflowError("effect_failed")
        if self.mode == "stall_before":
            self.entered.set()
            self.gate.wait(timeout=2)
            raise WorkflowError("timeout")
        effect_ref = secrets.token_hex(16)
        with store.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO synthetic_effect_ledger
                   (idempotency_key, effect_ref, binding_sha, recorded_at)
                   VALUES (?, ?, ?, ?)""",
                (idempotency_key, effect_ref, binding_sha, stamp),
            )
            row = connection.execute(
                "SELECT effect_ref FROM synthetic_effect_ledger WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise WorkflowError("operation_failed")
        recorded = row["effect_ref"]
        if self.mode == "uncertain":
            raise EffectUncertain()
        if self.mode in {"stall_after", "hold_after"}:
            self.entered.set()
            self.gate.wait(timeout=2)
        return recorded


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


# Cursor is navigation only, never an authorization or a reference requiring a live row.
def workflow_cursor(task: dict) -> str:
    return f"wf1|{task['created_at']}|{task['task_id']}"


def parse_workflow_cursor(cursor: str) -> tuple[str, str] | None:
    if cursor == "":
        return None
    if not isinstance(cursor, str) or len(cursor) > 80 or not re.fullmatch(
        r"wf1\|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?\+00:00\|[0-9a-f]{32}", cursor
    ):
        raise WorkflowError("schema_rejected")
    _, stamp, identifier = cursor.split("|")
    try:
        if _stamp(datetime.fromisoformat(stamp)) != stamp:
            raise ValueError
    except ValueError:
        raise WorkflowError("schema_rejected") from None
    return stamp, identifier


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
    def __init__(self, store: SQLiteMemoryStore, connector: FakeSyntheticConnector | None = None) -> None:
        if connector is not None and not isinstance(connector, FakeSyntheticConnector):
            raise WorkflowError("tool_blocked")
        self.store = store
        self.connector = connector or FakeSyntheticConnector()

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

    def page_tasks(self, owner: str, now: datetime, cursor: str = "") -> tuple[list[dict], bool]:
        """Read at most five rows; caller packs up to four within its wire budget."""
        _owner_time(owner, now)
        after = parse_workflow_cursor(cursor)
        with self.store.transaction() as connection:
            where = "owner=?"
            parameters = [owner]
            if after is not None:
                where += " AND (created_at, id) < (?, ?)"
                parameters.extend(after)
            rows = connection.execute(
                f"SELECT id FROM workflow_tasks WHERE {where} ORDER BY created_at DESC, id DESC LIMIT 5",
                parameters,
            ).fetchall()
            summaries = []
            for row in rows[:4]:
                task = self._public(connection, row["id"], include_result=False)
                # Fail closed for corrupt, noncanonical ordering keys.
                parse_workflow_cursor(workflow_cursor(task))
                summaries.append({key: task[key] for key in (
                    "task_id", "tool_id", "state", "arguments_sha", "created_at", "updated_at", "risk", "expected_effect"
                )})
            return summaries, len(rows) > 4

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
            arguments = self._stored_arguments(task)
            binding = self._effect_binding(spec, arguments, task)
            existing = connection.execute("SELECT * FROM workflow_approvals WHERE task_id=?", (task_id,)).fetchone()
            if (
                existing is not None
                and existing["used_at"] is None
                and existing["expires_at"] > stamp
                and existing["arguments_sha"] == expected_sha
                and existing["session_binding"] == session_ref
                and existing["grant_id"] == grant_id
                and self._binding_matches(existing, binding)
            ):
                return {
                    "expires_at": existing["expires_at"],
                    "arguments_sha": expected_sha,
                    "binding_sha": binding["binding_sha"],
                }
            expiry = _stamp(now + APPROVAL_TTL)
            approval_id = secrets.token_hex(16)
            connection.execute(
                """INSERT INTO workflow_approvals
                   (id, task_id, arguments_sha, session_binding, grant_id, expires_at, used_at,
                    bound_account, bound_connector, bound_tool, bound_destination, bound_effect, binding_sha)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET id=excluded.id, arguments_sha=excluded.arguments_sha,
                     session_binding=excluded.session_binding, grant_id=excluded.grant_id,
                     expires_at=excluded.expires_at, used_at=NULL,
                     bound_account=excluded.bound_account, bound_connector=excluded.bound_connector,
                     bound_tool=excluded.bound_tool, bound_destination=excluded.bound_destination,
                     bound_effect=excluded.bound_effect, binding_sha=excluded.binding_sha""",
                (
                    approval_id, task_id, expected_sha, session_ref, grant_id, expiry,
                    binding["account"], binding["connector"], binding["tool"], binding["destination"],
                    binding["presented_effect"], binding["binding_sha"],
                ),
            )
            connection.execute("UPDATE workflow_tasks SET updated_at=? WHERE id=?", (stamp, task_id))
            self._log(connection, task_id, stamp, "approval_issued")
            return {"expires_at": expiry, "arguments_sha": expected_sha, "binding_sha": binding["binding_sha"]}

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
            binding = self._effect_binding(spec, arguments, task)
            result_row = connection.execute("SELECT * FROM workflow_results WHERE task_id=?", (task_id,)).fetchone()
            approval = connection.execute("SELECT * FROM workflow_approvals WHERE task_id=?", (task_id,)).fetchone()
            if result_row is not None:
                if spec.approval_required and not self._approval_matches(approval, task, session_ref, grant_id, require_unused=False):
                    raise WorkflowError("grant_rejected")
                if spec.approval_required and not self._binding_matches(approval, binding):
                    raise WorkflowError("approval_rejected")
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
                if not self._approval_matches(approval, task, session_ref, grant_id, require_unused=True) or not self._binding_matches(approval, binding):
                    raise WorkflowError("approval_rejected")
                if spec.tool_id == "simulate_action" and not isinstance(self.connector, FakeSyntheticConnector):
                    raise WorkflowError("tool_blocked")
                changed = connection.execute(
                    "UPDATE workflow_approvals SET used_at=? WHERE task_id=? AND used_at IS NULL AND expires_at>?",
                    (stamp, task_id, stamp),
                ).rowcount
                if changed != 1:
                    raise WorkflowError("approval_replayed")
                if spec.tool_id == "simulate_action":
                    self._open_outbox(connection, task, binding, stamp)
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

        token = None
        if spec.tool_id == "simulate_action":
            token = _EFFECT_DISPATCH.set({
                "store": self.store,
                "connector": self.connector,
                "idempotency_key": idempotency_key,
                "binding": binding,
                "stamp": stamp,
            })
        try:
            try:
                output, attempts = self._run_tool(spec, arguments)
            except WorkflowError as exc:
                self._settle_failed_effect(owner, task_id, exc.code)
                raise
        finally:
            if token is not None:
                _EFFECT_DISPATCH.reset(token)
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
            if spec.tool_id == "simulate_action":
                effect_ref = output.get("effect_ref") if isinstance(output, dict) else None
                updated = connection.execute(
                    """UPDATE synthetic_effect_outbox
                       SET state='succeeded', effect_ref=?, updated_at=?
                       WHERE task_id=? AND state='unknown'""",
                    (effect_ref, _stamp(datetime.now(timezone.utc)), task_id),
                ).rowcount
                if updated != 1:
                    raise WorkflowError("state_rejected")
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
            captured = contextvars.copy_context()
            future = pool.submit(captured.run, self._execute_once, spec, arguments)
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
            dispatch = _EFFECT_DISPATCH.get()
            if not isinstance(dispatch, dict):
                raise WorkflowError("tool_blocked")
            connector = dispatch["connector"]
            if not isinstance(connector, FakeSyntheticConnector):
                raise WorkflowError("tool_blocked")
            binding = dispatch["binding"]
            if (
                binding["connector"] != "synthetic-mail"
                or binding["tool"] != "simulate_action"
                or binding["destination"] != "synthetic-outbox"
                or binding["account"] != "operator@example.test"
            ):
                raise WorkflowError("tool_blocked")
            try:
                effect_ref = connector.apply(
                    dispatch["store"],
                    idempotency_key=dispatch["idempotency_key"],
                    binding_sha=binding["binding_sha"],
                    stamp=dispatch["stamp"],
                )
            except EffectUncertain:
                raise WorkflowError("effect_unknown") from None
            return {
                "simulated": True, "sent": False, "data_sent": [],
                "target": arguments["target"], "effect_ref": effect_ref,
            }
        raise WorkflowError("tool_blocked")

    def effect_status(self, owner: str, task_id: str, now: datetime) -> dict:
        _owner_time(owner, now)
        with self.store.transaction() as connection:
            self._require(connection, owner, task_id)
            row = connection.execute(
                "SELECT state, effect_ref FROM synthetic_effect_outbox WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise WorkflowError("effect_absent")
        return {"state": row["state"], "effect_ref": row["effect_ref"]}

    def reconcile_effects(self, owner: str, now: datetime) -> list[dict]:
        """Resolve unknown rows from the ledger. This method never calls the connector."""
        stamp = _owner_time(owner, now)
        if not isinstance(self.connector, FakeSyntheticConnector):
            raise WorkflowError("tool_blocked")
        calls_before = self.connector.calls
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM synthetic_effect_outbox WHERE state='unknown' ORDER BY created_at, id"
            ).fetchall()
            results = []
            for row in rows:
                ledger = connection.execute(
                    "SELECT effect_ref, binding_sha FROM synthetic_effect_ledger WHERE idempotency_key=?",
                    (row["idempotency_key"],),
                ).fetchone()
                if ledger is not None and hmac.compare_digest(ledger["binding_sha"], row["binding_sha"]):
                    connection.execute(
                        """UPDATE synthetic_effect_outbox
                           SET state='succeeded', effect_ref=?, updated_at=?
                           WHERE id=? AND state='unknown'""",
                        (ledger["effect_ref"], stamp, row["id"]),
                    )
                    self._materialize_recorded_effect(connection, row, ledger["effect_ref"], stamp)
                    results.append({"task_id": row["task_id"], "state": "succeeded", "effect_ref": ledger["effect_ref"]})
                elif ledger is not None:
                    results.append({"task_id": row["task_id"], "state": "unknown", "effect_ref": ledger["effect_ref"]})
                else:
                    connection.execute(
                        """UPDATE synthetic_effect_outbox
                           SET state='failed', updated_at=?
                           WHERE id=? AND state='unknown'""",
                        (stamp, row["id"]),
                    )
                    results.append({"task_id": row["task_id"], "state": "failed", "effect_ref": None})
        if self.connector.calls != calls_before:
            raise WorkflowError("tool_blocked")
        return results

    def _settle_failed_effect(self, owner: str, task_id: str, code: str) -> None:
        if code == "effect_unknown":
            self._mark_unknown(owner, task_id)
            return
        self._mark_failed(owner, task_id)
        if code == "timeout" or self._ledger_has(task_id):
            return
        self._set_outbox_state(task_id, "failed")

    def _mark_unknown(self, owner: str, task_id: str) -> None:
        stamp = _stamp(datetime.now(timezone.utc))
        with self.store.transaction() as connection:
            task = self._require(connection, owner, task_id)
            if task["state"] == "running":
                connection.execute("UPDATE workflow_tasks SET state='interrupted', updated_at=? WHERE id=?", (stamp, task_id))
                connection.execute(
                    "UPDATE workflow_executions SET phase='interrupted' WHERE task_id=? AND phase='open'",
                    (task_id,),
                )
                self._log(connection, task_id, stamp, "execution_interrupted")

    def _set_outbox_state(self, task_id: str, state: str) -> None:
        if state not in {"succeeded", "failed", "unknown"}:
            raise WorkflowError("log_event_rejected")
        stamp = _stamp(datetime.now(timezone.utc))
        with self.store.transaction() as connection:
            connection.execute(
                """UPDATE synthetic_effect_outbox SET state=?, updated_at=?
                   WHERE task_id=? AND state='unknown'""",
                (state, stamp, task_id),
            )

    def _ledger_has(self, task_id: str) -> bool:
        with self.store.transaction() as connection:
            row = connection.execute(
                """SELECT 1 FROM synthetic_effect_ledger AS ledger
                   JOIN synthetic_effect_outbox AS box ON box.idempotency_key = ledger.idempotency_key
                   WHERE box.task_id=?""",
                (task_id,),
            ).fetchone()
        return row is not None

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

    def _effect_binding(self, spec: ToolSpec, arguments: dict, task) -> dict:
        preview: dict = {}
        if task["preview_json"]:
            try:
                parsed = json.loads(task["preview_json"])
            except (TypeError, ValueError):
                raise WorkflowError("task_corrupt") from None
            if not isinstance(parsed, dict):
                raise WorkflowError("task_corrupt")
            preview = parsed
        consequence = preview.get("consequence", "")
        if not isinstance(consequence, str):
            raise WorkflowError("task_corrupt")
        fields = {
            "review_sha": task["arguments_sha"],
            "account": arguments.get("account", "") if isinstance(arguments.get("account", ""), str) else "",
            "connector": arguments.get("service", "") if isinstance(arguments.get("service", ""), str) else "",
            "tool": spec.tool_id,
            "destination": arguments.get("target", "") if isinstance(arguments.get("target", ""), str) else "",
            "presented_effect": f"{spec.expected_effect}|{consequence}",
        }
        return {**fields, "binding_sha": canonical_sha(fields)}

    def _approval_binding_intact(self, approval) -> bool:
        if approval is None:
            return False
        fields = {
            "review_sha": approval["arguments_sha"],
            "account": approval["bound_account"],
            "connector": approval["bound_connector"],
            "tool": approval["bound_tool"],
            "destination": approval["bound_destination"],
            "presented_effect": approval["bound_effect"],
        }
        digest = approval["binding_sha"]
        if not isinstance(digest, str) or any(not isinstance(value, str) or not value for value in fields.values()):
            return False
        return hmac.compare_digest(canonical_sha(fields), digest)

    def _binding_matches(self, approval, binding: dict) -> bool:
        if not self._approval_binding_intact(approval):
            return False
        return hmac.compare_digest(approval["binding_sha"], binding["binding_sha"])

    def _open_outbox(self, connection, task, binding: dict, stamp: str) -> None:
        if (
            binding["tool"] != "simulate_action"
            or binding["connector"] != "synthetic-mail"
            or binding["destination"] != "synthetic-outbox"
            or binding["account"] != "operator@example.test"
        ):
            raise WorkflowError("tool_blocked")
        existing = connection.execute(
            "SELECT state FROM synthetic_effect_outbox WHERE task_id=?", (task["id"],)
        ).fetchone()
        if existing is not None:
            if existing["state"] == "unknown":
                return
            raise WorkflowError("approval_replayed")
        connection.execute(
            """INSERT INTO synthetic_effect_outbox (
                   id, task_id, idempotency_key, binding_sha, review_sha, account, connector,
                   tool_id, destination, presented_effect, catalog_effect, state, effect_ref,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown', NULL, ?, ?)""",
            (
                secrets.token_hex(16), task["id"], task["idempotency_key"], binding["binding_sha"],
                binding["review_sha"], binding["account"], binding["connector"], binding["tool"],
                binding["destination"], binding["presented_effect"], TOOLS[binding["tool"]].expected_effect,
                stamp, stamp,
            ),
        )

    def _materialize_recorded_effect(self, connection, row, effect_ref: str, stamp: str) -> None:
        task = connection.execute("SELECT * FROM workflow_tasks WHERE id=?", (row["task_id"],)).fetchone()
        if task is None:
            return
        existing = connection.execute(
            "SELECT result_sha FROM workflow_results WHERE task_id=?", (row["task_id"],)
        ).fetchone()
        if existing is None:
            output = {
                "simulated": True, "sent": False, "data_sent": [],
                "target": row["destination"], "effect_ref": effect_ref,
            }
            result_sha = canonical_sha({"effect": row["catalog_effect"], "tool_id": row["tool_id"], "output": output})
            connection.execute(
                "INSERT INTO workflow_results(task_id, effect, output_json, result_sha, attempts) VALUES (?, ?, ?, ?, ?)",
                (
                    row["task_id"], row["catalog_effect"],
                    json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    result_sha, 1,
                ),
            )
        if task["state"] == "cancelled":
            return
        connection.execute(
            "UPDATE workflow_executions SET phase='committed', attempts=1 WHERE task_id=?",
            (row["task_id"],),
        )
        changed = connection.execute(
            """UPDATE workflow_tasks SET state='succeeded', updated_at=?
               WHERE id=? AND state IN ('running', 'interrupted', 'failed')""",
            (stamp, row["task_id"]),
        ).rowcount
        if changed == 1:
            self._log(connection, row["task_id"], stamp, "execution_succeeded")

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
