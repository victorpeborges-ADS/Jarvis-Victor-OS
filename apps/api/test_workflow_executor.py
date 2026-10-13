from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

import workflow_executor as workflow_module
from memory_store import SQLiteMemoryStore
from workflow_executor import WorkflowError, WorkflowExecutor, TransientFailure, canonical_sha, session_binding

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
SIMULATION = {
    "tool_id": "simulate_action",
    "arguments": {
        "service": "synthetic-mail",
        "account": "operator@example.test",
        "target": "synthetic-outbox",
        "payload": {"subject": "Aviso local", "body": "Texto sintético de teste"},
    },
}


def ready(path):
    store = SQLiteMemoryStore(path / "private" / "memory.sqlite3")
    store.initialize()
    return store, WorkflowExecutor(store)


def approve(executor, task, *, binding="sessao-sintetica", grant="grant-sintetico", now=NOW):
    return executor.approve(
        "owner", task["task_id"], task["arguments_sha"],
        session_binding(binding), grant, now,
    )


def execute(executor, task, *, binding="sessao-sintetica", grant="grant-sintetico", now=NOW):
    return executor.execute(
        "owner", task["task_id"], task["idempotency_key"],
        session_binding(binding), grant, now,
    )


def test_closed_tool_catalog_schema_preview_and_disabled_side_effects(tmp_path):
    _store, executor = ready(tmp_path)
    with pytest.raises(WorkflowError, match="tool_blocked"):
        executor.submit("owner", {"tool_id": "send_message", "arguments": {}}, "idem-send-001", NOW)
    with pytest.raises(WorkflowError, match="schema_rejected"):
        executor.submit("owner", {"tool_id": "draft_note", "arguments": {"title": "x", "body": "y", "url": "https://bad.test"}}, "idem-draft-01", NOW)
    with pytest.raises(WorkflowError, match="schema_rejected"):
        executor.submit("owner", {"tool_id": "draft_note", "arguments": {"method": "POST", "url": "https://bad.test"}}, "idem-generic-01", NOW)
    with pytest.raises(WorkflowError, match="recommendation_rejected"):
        executor.submit("owner", {"tool_id": "draft_note", "arguments": {}, "url": "https://bad.test"}, "idem-generic-02", NOW)
    with pytest.raises(WorkflowError, match="schema_rejected"):
        executor.submit("owner", {"tool_id": "draft_note", "arguments": {"title": "Nota", "body": "Authorization: Bearer abcdefghijklmnop"}}, "idem-secret-001", NOW)
    task = executor.submit("owner", SIMULATION, "idem-simulation-1", NOW)
    assert task["state"] == "awaiting_approval"
    assert task["preview"]["service"] == "E-mail sintético (simulação local)"
    assert task["preview"]["payload"] == SIMULATION["arguments"]["payload"]
    assert task["preview"]["data_sent"] == []
    assert task["expected_effect"] == "simulação local sem envio"


def test_exact_parameters_single_use_expiry_and_process_restart_binding(tmp_path, monkeypatch):
    store, executor = ready(tmp_path)
    raw_token = "synthetic-session-secret-token"
    monkeypatch.setattr(workflow_module, "_SESSION_BINDING_KEY", b"a" * 32)
    old_binding = session_binding(raw_token)
    task = executor.submit("owner", SIMULATION, "idem-restart-001", NOW)
    altered_sha = canonical_sha({"tool_id": "simulate_action", "arguments": {**SIMULATION["arguments"], "target": "altered"}})
    with pytest.raises(WorkflowError, match="parameters_changed"):
        executor.approve("owner", task["task_id"], altered_sha, old_binding, "grant-old", NOW)
    approve(executor, task, binding=raw_token, grant="grant-old")
    with store.transaction() as connection:
        connection.execute(
            "UPDATE workflow_tasks SET arguments_json=? WHERE id=?",
            (json.dumps({**SIMULATION["arguments"], "target": "altered"}), task["task_id"]),
        )
        stored = connection.execute("SELECT session_binding FROM workflow_approvals").fetchone()[0]
        assert raw_token not in stored
    with pytest.raises(WorkflowError, match="task_corrupt"):
        execute(executor, task, binding=raw_token, grant="grant-old")
    with store.transaction() as connection:
        connection.execute(
            "UPDATE workflow_tasks SET arguments_json=? WHERE id=?",
            (json.dumps(SIMULATION["arguments"], ensure_ascii=False, sort_keys=True, separators=(",", ":")), task["task_id"]),
        )
    with pytest.raises(WorkflowError, match="approval_expired"):
        execute(executor, task, binding=raw_token, grant="grant-old", now=NOW + timedelta(seconds=61))
    monkeypatch.setattr(workflow_module, "_SESSION_BINDING_KEY", b"b" * 32)
    new_ref = session_binding("session-after-restart")
    with pytest.raises(WorkflowError, match="approval_rejected"):
        executor.execute("owner", task["task_id"], task["idempotency_key"], new_ref, "grant-new", NOW)
    executor.approve("owner", task["task_id"], task["arguments_sha"], new_ref, "grant-new", NOW)
    done = executor.execute("owner", task["task_id"], task["idempotency_key"], new_ref, "grant-new", NOW)
    assert done["state"] == "succeeded" and done["result"]["sent"] is False


def test_execution_reservation_is_atomic_retry_safe_and_lost_response_replays(tmp_path):
    _store, executor = ready(tmp_path)
    task = executor.submit("owner", SIMULATION, "idem-race-0001", NOW)
    approve(executor, task)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def held_handler(spec, arguments):
        calls.append(spec.tool_id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=3)
            return {"simulated": True, "sent": False, "data_sent": [], "target": arguments["target"]}
        raise AssertionError("segunda chamada executou o efeito")

    executor._execute_once = held_handler
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, executor, task)
        assert entered.wait(timeout=3)
        second = pool.submit(execute, executor, task)
        with pytest.raises(WorkflowError, match="state_rejected"):
            second.result(timeout=3)
        release.set()
        completed = first.result(timeout=3)
    assert calls == ["simulate_action"]
    assert completed["replayed"] is False
    replay = execute(executor, task)
    assert replay["replayed"] is True
    assert replay["result_sha"] == completed["result_sha"]
    assert calls == ["simulate_action"]
    with _store.transaction() as connection:
        connection.execute("UPDATE workflow_results SET result_sha=? WHERE task_id=?", ("0" * 64, task["task_id"]))
    with pytest.raises(WorkflowError, match="result_corrupt"):
        executor.detail("owner", task["task_id"], NOW)


def test_local_tool_timeout_fails_without_a_late_persisted_result(tmp_path):
    store, executor = ready(tmp_path)
    task = executor.submit("owner", SIMULATION, "idem-timeout-001", NOW)
    approve(executor, task)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_local_tool(_spec, _arguments):
        started.set()
        release.wait(timeout=2)
        finished.set()
        return {"simulated": True, "sent": False, "data_sent": [], "target": "synthetic-outbox"}

    executor._execute_once = slow_local_tool
    with pytest.raises(WorkflowError, match="timeout"):
        execute(executor, task)
    assert started.is_set()
    assert executor.detail("owner", task["task_id"], NOW)["state"] == "failed"
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM workflow_results WHERE task_id=?", (task["task_id"],)).fetchone()[0] == 0
    release.set()
    assert finished.wait(timeout=2)


def test_crash_recovery_retry_policy_pause_resume_and_redacted_event_log(tmp_path):
    store, executor = ready(tmp_path)
    task = executor.submit("owner", SIMULATION, "idem-crash-0001", NOW)
    approve(executor, task)
    with store.transaction() as connection:
        connection.execute("UPDATE workflow_tasks SET state='running' WHERE id=?", (task["task_id"],))
        connection.execute(
            "INSERT INTO workflow_executions(id,task_id,phase,attempts,created_at) VALUES (?,?,?,?,?)",
            ("f" * 32, task["task_id"], "open", 1, NOW.isoformat()),
        )
    assert executor.recover(NOW) == 1
    interrupted = executor.detail("owner", task["task_id"], NOW)
    assert interrupted["state"] == "interrupted"
    with pytest.raises(WorkflowError, match="approval_required"):
        executor.resume("owner", task["task_id"], NOW)
    executor.approve("owner", task["task_id"], task["arguments_sha"], session_binding("sessao-sintetica"), "grant-sintetico", NOW)
    calls = []

    def flaky(spec, arguments):
        calls.append(1)
        if len(calls) == 1:
            raise TransientFailure()
        return {"simulated": True, "sent": False, "data_sent": [], "target": arguments["target"]}

    executor._execute_once = flaky
    completed = execute(executor, task)
    assert completed["attempts"] == 2 and len(calls) == 2
    executor._execute_once = WorkflowExecutor._execute_once

    draft = executor.submit("owner", {"tool_id": "draft_note", "arguments": {"title": "Ideia", "body": "conteúdo sensível de teste"}}, "idem-pause-0001", NOW)
    assert executor.pause("owner", draft["task_id"], NOW)["state"] == "paused"
    assert executor.resume("owner", draft["task_id"], NOW)["state"] == "proposed"
    saved = executor.execute("owner", draft["task_id"], draft["idempotency_key"], session_binding("sessao-sintetica"), None, NOW)
    assert saved["result"]["body"] == "conteúdo sensível de teste"
    cancelled_task = executor.submit("owner", {"tool_id": "draft_note", "arguments": {"title": "Descartar", "body": "Rascunho cancelável"}}, "idem-cancel-0001", NOW)
    assert executor.cancel("owner", cancelled_task["task_id"], NOW)["state"] == "cancelled"
    with store.transaction() as connection:
        log_text = " ".join(row[0] for row in connection.execute("SELECT event FROM workflow_log"))
        assert "conteúdo sensível de teste" not in log_text
        assert connection.execute("SELECT state FROM workflow_tasks WHERE id=?", (draft["task_id"],)).fetchone()[0] == "succeeded"
