from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
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


def ready(path, encrypted_store_factory):
    store = encrypted_store_factory(path / "private" / "memory.sqlite3")
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


def effect_rows(store):
    with store.transaction() as connection:
        ledger = connection.execute("SELECT COUNT(*) FROM synthetic_effect_ledger").fetchone()[0]
        outbox = connection.execute("SELECT COUNT(*) FROM synthetic_effect_outbox").fetchone()[0]
    return ledger, outbox


def submit(executor, key):
    return executor.submit("owner", SIMULATION, key, NOW)


def test_closed_tool_catalog_schema_preview_and_disabled_side_effects(tmp_path, encrypted_store_factory):
    _store, executor = ready(tmp_path, encrypted_store_factory)
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


def test_exact_parameters_single_use_expiry_and_process_restart_binding(tmp_path, monkeypatch, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
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


def test_execution_reservation_is_atomic_retry_safe_and_lost_response_replays(tmp_path, encrypted_store_factory):
    _store, executor = ready(tmp_path, encrypted_store_factory)
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


def test_local_tool_timeout_fails_without_a_late_persisted_result(tmp_path, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
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


def test_crash_recovery_retry_policy_pause_resume_and_redacted_event_log(tmp_path, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
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


def test_approval_binds_review_account_connector_tool_destination_and_presented_effect(tmp_path, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
    task = submit(executor, "idem-bind-0001")
    first = approve(executor, task)
    second = approve(executor, task)
    assert first == second
    assert first["arguments_sha"] == task["arguments_sha"]
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM workflow_approvals WHERE task_id=?", (task["task_id"],)
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM workflow_approvals WHERE task_id=?", (task["task_id"],)).fetchone()[0] == 1
    assert row["arguments_sha"] == task["arguments_sha"]
    assert row["bound_account"] == "operator@example.test"
    assert row["bound_connector"] == "synthetic-mail"
    assert row["bound_tool"] == "simulate_action"
    assert row["bound_destination"] == "synthetic-outbox"
    assert row["bound_effect"].startswith("simulação local sem envio|")
    assert row["binding_sha"] == first["binding_sha"]

    def refuse(key, mutate, code):
        current = submit(executor, key)
        approve(executor, current)
        mutate(store, current)
        with pytest.raises(WorkflowError, match=code):
            execute(executor, current)
        assert effect_rows(store) == (0, 0)
        with store.transaction() as connection:
            assert connection.execute(
                "SELECT used_at FROM workflow_approvals WHERE task_id=?", (current["task_id"],)
            ).fetchone()[0] is None

    def payload_swap(current_store, current):
        changed = {
            **SIMULATION["arguments"],
            "payload": {"subject": "Outro aviso", "body": "Outro texto sintético"},
        }
        spec, arguments = workflow_module.accept_recommendation(
            {"tool_id": "simulate_action", "arguments": changed}
        )
        digest = canonical_sha({"tool_id": spec.tool_id, "arguments": arguments})
        raw = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        with current_store.transaction() as connection:
            connection.execute(
                "UPDATE workflow_tasks SET arguments_json=?, arguments_sha=? WHERE id=?",
                (raw, digest, current["task_id"]),
            )

    def preview_swap(current_store, current):
        with current_store.transaction() as connection:
            preview = json.loads(connection.execute(
                "SELECT preview_json FROM workflow_tasks WHERE id=?", (current["task_id"],)
            ).fetchone()[0])
            preview["consequence"] = "Efeito apresentado diferente do aprovado"
            connection.execute(
                "UPDATE workflow_tasks SET preview_json=? WHERE id=?",
                (json.dumps(preview, ensure_ascii=False, sort_keys=True), current["task_id"]),
            )

    def account_swap(current_store, current):
        changed = {**SIMULATION["arguments"], "account": "other@example.test"}
        with current_store.transaction() as connection:
            connection.execute(
                "UPDATE workflow_tasks SET arguments_json=?, arguments_sha=? WHERE id=?",
                (json.dumps(changed, sort_keys=True), "ab" * 32, current["task_id"]),
            )

    def connector_swap(current_store, current):
        changed = {**SIMULATION["arguments"], "service": "gmail"}
        with current_store.transaction() as connection:
            connection.execute(
                "UPDATE workflow_tasks SET arguments_json=?, arguments_sha=? WHERE id=?",
                (json.dumps(changed, sort_keys=True), "cd" * 32, current["task_id"]),
            )

    def destination_swap(current_store, current):
        changed = {**SIMULATION["arguments"], "target": "inbox-real"}
        with current_store.transaction() as connection:
            connection.execute(
                "UPDATE workflow_tasks SET arguments_json=?, arguments_sha=? WHERE id=?",
                (json.dumps(changed, sort_keys=True), "ef" * 32, current["task_id"]),
            )

    def tool_swap(current_store, current):
        spec, arguments = workflow_module.accept_recommendation(
            {"tool_id": "draft_note", "arguments": {"title": "Nota", "body": "Texto local"}}
        )
        digest = canonical_sha({"tool_id": spec.tool_id, "arguments": arguments})
        raw = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        with current_store.transaction() as connection:
            connection.execute(
                "UPDATE workflow_tasks SET tool_id=?, arguments_json=?, arguments_sha=? WHERE id=?",
                ("draft_note", raw, digest, current["task_id"]),
            )

    def approval_account_swap(current_store, current):
        with current_store.transaction() as connection:
            connection.execute(
                "UPDATE workflow_approvals SET bound_account=? WHERE task_id=?",
                ("other@example.test", current["task_id"]),
            )

    refuse("idem-swap-hash01", payload_swap, "approval_rejected")
    refuse("idem-swap-show01", preview_swap, "approval_rejected")
    refuse("idem-swap-acct01", account_swap, "task_corrupt")
    refuse("idem-swap-conn01", connector_swap, "task_corrupt")
    refuse("idem-swap-dest01", destination_swap, "task_corrupt")
    refuse("idem-swap-tool01", tool_swap, "state_rejected")
    refuse("idem-swap-bind01", approval_account_swap, "approval_rejected")

    original = workflow_module.TOOLS["simulate_action"]
    shown = submit(executor, "idem-swap-eff001")
    approve(executor, shown)
    workflow_module.TOOLS["simulate_action"] = workflow_module.ToolSpec(
        original.tool_id, original.schema, original.permission, original.risk,
        original.timeout_ms, original.limit, original.retry, "efeito apresentado alterado",
        original.enabled, original.approval_required,
    )
    try:
        with pytest.raises(WorkflowError, match="approval_rejected"):
            execute(executor, shown)
    finally:
        workflow_module.TOOLS["simulate_action"] = original
    assert effect_rows(store) == (0, 0)


def test_cancel_pause_and_expiry_do_not_record_a_synthetic_effect(tmp_path, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
    cancelled = submit(executor, "idem-cancel-009")
    approve(executor, cancelled)
    assert executor.cancel("owner", cancelled["task_id"], NOW)["state"] == "cancelled"
    with pytest.raises(WorkflowError, match="state_rejected"):
        execute(executor, cancelled)

    paused = submit(executor, "idem-pause-009")
    approve(executor, paused)
    assert executor.pause("owner", paused["task_id"], NOW)["state"] == "paused"
    with pytest.raises(WorkflowError, match="state_rejected"):
        execute(executor, paused)

    expired = submit(executor, "idem-expire-09")
    approve(executor, expired)
    with pytest.raises(WorkflowError, match="approval_expired"):
        execute(executor, expired, now=NOW + timedelta(seconds=61))
    with pytest.raises(WorkflowError, match="effect_absent"):
        executor.effect_status("owner", expired["task_id"], NOW)
    assert effect_rows(store) == (0, 0)


def test_synthetic_outbox_replay_failure_unknown_and_timeout_do_not_duplicate(tmp_path, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
    connector = executor.connector

    saved = submit(executor, "idem-replay-001")
    approve(executor, saved)
    done = execute(executor, saved)
    assert done["replayed"] is False and done["result"]["sent"] is False
    assert executor.effect_status("owner", saved["task_id"], NOW)["state"] == "succeeded"
    replay = execute(executor, saved)
    assert replay["replayed"] is True and replay["result_sha"] == done["result_sha"]
    assert connector.calls == 1
    assert effect_rows(store) == (1, 1)
    assert executor.reconcile_effects("owner", NOW) == []
    assert connector.calls == 1 and effect_rows(store) == (1, 1)

    failed = submit(executor, "idem-fail-0001")
    approve(executor, failed)
    connector.mode = "fail"
    with pytest.raises(WorkflowError, match="effect_failed"):
        execute(executor, failed)
    assert executor.effect_status("owner", failed["task_id"], NOW)["state"] == "failed"
    assert executor.detail("owner", failed["task_id"], NOW)["state"] == "failed"
    calls_after_fail = connector.calls
    assert executor.reconcile_effects("owner", NOW) == []
    with pytest.raises(WorkflowError, match="state_rejected"):
        execute(executor, failed)
    assert connector.calls == calls_after_fail
    assert effect_rows(store) == (1, 2)

    unknown = submit(executor, "idem-unknown-01")
    approve(executor, unknown)
    connector.mode = "uncertain"
    with pytest.raises(WorkflowError, match="effect_unknown"):
        execute(executor, unknown)
    assert executor.effect_status("owner", unknown["task_id"], NOW)["state"] == "unknown"
    assert executor.detail("owner", unknown["task_id"], NOW)["state"] == "interrupted"
    calls_after_unknown = connector.calls
    with pytest.raises(WorkflowError, match="approval_rejected"):
        execute(executor, unknown)
    resolved = executor.reconcile_effects("owner", NOW)
    assert resolved == [{
        "task_id": unknown["task_id"],
        "state": "succeeded",
        "effect_ref": executor.effect_status("owner", unknown["task_id"], NOW)["effect_ref"],
    }]
    assert executor.reconcile_effects("owner", NOW) == []
    replayed_unknown = execute(executor, unknown)
    assert replayed_unknown["replayed"] is True
    assert connector.calls == calls_after_unknown
    assert effect_rows(store) == (2, 3)

    lost = submit(executor, "idem-timeout-02")
    approve(executor, lost)
    connector.mode = "stall_before"
    connector.entered.clear()
    connector.gate.set()
    with pytest.raises(WorkflowError, match="timeout"):
        execute(executor, lost)
    assert executor.effect_status("owner", lost["task_id"], NOW)["state"] == "unknown"
    calls_after_lost = connector.calls
    assert executor.reconcile_effects("owner", NOW) == [{
        "task_id": lost["task_id"], "state": "failed", "effect_ref": None,
    }]
    assert executor.effect_status("owner", lost["task_id"], NOW)["state"] == "failed"
    assert connector.calls == calls_after_lost

    late = submit(executor, "idem-timeout-03")
    approve(executor, late)
    connector.mode = "stall_after"
    connector.entered.clear()
    connector.gate.clear()
    with pytest.raises(WorkflowError, match="timeout"):
        execute(executor, late)
    assert connector.entered.is_set()
    assert executor.effect_status("owner", late["task_id"], NOW)["state"] == "unknown"
    calls_after_late = connector.calls
    ledger_before = effect_rows(store)[0]
    connector.gate.set()
    resolved_late = executor.reconcile_effects("owner", NOW)
    assert resolved_late[0]["state"] == "succeeded"
    assert resolved_late[0]["task_id"] == late["task_id"]
    assert effect_rows(store)[0] == ledger_before
    assert connector.calls == calls_after_late
    replayed_late = execute(executor, late)
    assert replayed_late["replayed"] is True
    assert connector.calls == calls_after_late
    assert effect_rows(store)[0] == ledger_before


def test_concurrent_dispatch_records_one_synthetic_effect(tmp_path, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
    connector = executor.connector
    connector.mode = "hold_after"
    task = submit(executor, "idem-race-out-1")
    approve(executor, task)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, executor, task)
        assert connector.entered.wait(timeout=3)
        second = pool.submit(execute, executor, task)
        with pytest.raises(WorkflowError, match="state_rejected"):
            second.result(timeout=3)
        connector.gate.set()
        completed = first.result(timeout=3)
    assert completed["replayed"] is False and completed["result"]["sent"] is False
    assert connector.calls == 1
    assert effect_rows(store) == (1, 1)
    replay = execute(executor, task)
    assert replay["replayed"] is True
    assert connector.calls == 1 and effect_rows(store) == (1, 1)


def test_confirmed_effect_stays_succeeded_when_the_task_is_cancelled(tmp_path, encrypted_store_factory):
    store, executor = ready(tmp_path, encrypted_store_factory)
    connector = executor.connector
    connector.mode = "uncertain"
    task = submit(executor, "idem-cancel-unk")
    approve(executor, task)
    with pytest.raises(WorkflowError, match="effect_unknown"):
        execute(executor, task)
    assert executor.cancel("owner", task["task_id"], NOW)["state"] == "cancelled"
    calls = connector.calls
    resolved = executor.reconcile_effects("owner", NOW)
    assert resolved[0]["state"] == "succeeded"
    assert executor.effect_status("owner", task["task_id"], NOW)["state"] == "succeeded"
    assert executor.detail("owner", task["task_id"], NOW)["state"] == "cancelled"
    assert connector.calls == calls
    assert effect_rows(store) == (1, 1)


def test_fake_connector_does_not_open_network_or_shell_and_real_effects_stay_disabled(tmp_path, monkeypatch, encrypted_store_factory):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("efeito externo")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)

    store, executor = ready(tmp_path, encrypted_store_factory)
    for tool_id, key in (
        ("send_message", "idem-block-send"),
        ("pay", "idem-block-pay1"),
        ("delete_record", "idem-block-del1"),
        ("invite_member", "idem-block-inv1"),
    ):
        with pytest.raises(WorkflowError, match="tool_blocked"):
            executor.submit("owner", {"tool_id": tool_id, "arguments": {}}, key, NOW)
    task = submit(executor, "idem-local-only")
    approve(executor, task)
    done = execute(executor, task)
    assert done["result"]["sent"] is False and done["result"]["data_sent"] == []
    assert effect_rows(store) == (1, 1)
    assert executor.connector.calls == 1
