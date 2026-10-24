"""J23: loop somente leitura com provider falso."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from conversation_gateway import APP_RESPONSE_MAX_BYTES, Budget, ManualClock
from local_captures import create_capture
from local_security import put_session_for_tests, reset_state
from memory_categories import record_memory
from memory_store import SQLiteMemoryStore
from read_only_tool_loop import (
    FinalAnswer,
    ReadOnlyToolLoop,
    ScriptedPlanner,
    ToolCall,
    encoded_tool_loop_body,
)

TOKEN = "sessao-sintetica"
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


def _budget(**overrides: object) -> Budget:
    values = {
        "max_seconds": 5,
        "max_tokens": 32,
        "max_attempts": 3,
        "max_calls": 4,
        "max_identical": 2,
    }
    values.update(overrides)
    return Budget(**values)


def _fields(**overrides: object) -> dict[str, object]:
    values = {
        "conversation_id": "conversa-a",
        "question": "qual fato",
        "domain_id": "dom_synthetic_a",
    }
    values.update(overrides)
    return values


def _store(path: Path, encrypted_store_factory) -> SQLiteMemoryStore:
    store = encrypted_store_factory(path)
    store.initialize()
    assert path.read_bytes().startswith(b"JVSDB\x00\x01\x00")
    return store


def _open_session() -> None:
    reset_state()
    put_session_for_tests(TOKEN, "owner", "csrf-sintetico")


def _loop(store, steps, clock=None) -> tuple[ScriptedPlanner, ReadOnlyToolLoop]:
    planner = ScriptedPlanner(steps)
    return planner, ReadOnlyToolLoop(store, planner, clock=clock or ManualClock())


def test_read_returns_only_the_stored_snippet_and_cost_stays_unmeasured(tmp_path, encrypted_store_factory):
    _open_session()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = create_capture(store, "owner", "prazo de sexta", NOW)
    planner, loop = _loop(store, [
        ToolCall("read_capture", {"capture_id": created["id"]}),
        FinalAnswer("prazo de sexta", (created["id"],)),
    ])
    result = loop.run(TOKEN, _fields(), _budget())
    assert result.status == "evidence"
    assert result.text == "prazo de sexta"
    assert result.source_ids == (created["id"],)
    assert result.tools_executed == 1
    assert result.cost == "unmeasured"
    assert result.cost != "0"
    assert planner.invocations == 2


def test_unknown_tool_stops_without_a_read(tmp_path, encrypted_store_factory):
    _open_session()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = create_capture(store, "owner", "nao enviar", NOW)
    planner, loop = _loop(store, [
        ToolCall("send_message", {"capture_id": created["id"]}),
    ])
    result = loop.run(TOKEN, _fields(), _budget())
    assert result.status == "unknown_tool"
    assert result.reason == "send_message"
    assert result.text == ""
    assert result.tools_executed == 0
    assert planner.invocations == 1
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM local_captures").fetchone()[0] == 1


def test_extra_field_stops_without_a_read(tmp_path, encrypted_store_factory):
    _open_session()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = create_capture(store, "owner", "campo fechado", NOW)
    _planner, loop = _loop(store, [
        ToolCall("read_capture", {"capture_id": created["id"], "url": "http://example.test"}),
    ])
    result = loop.run(TOKEN, _fields(), _budget())
    assert result.status == "invalid_request"
    assert result.reason == "extra_field"
    assert result.tools_executed == 0
    assert result.text == ""


def test_repeated_read_stops_the_loop(tmp_path, encrypted_store_factory):
    _open_session()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = create_capture(store, "owner", "ler uma vez", NOW)
    call = ToolCall("read_capture", {"capture_id": created["id"]})
    _planner, loop = _loop(store, [call, call])
    result = loop.run(TOKEN, _fields(), _budget())
    assert result.status == "loop_detected"
    assert result.reason == "identical"
    assert result.tools_executed == 1
    assert result.text == ""


def test_deadline_discards_the_tool_and_the_body(tmp_path, encrypted_store_factory):
    _open_session()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = create_capture(store, "owner", "fora do prazo", NOW)
    clock = ManualClock()

    def steps():
        return [
            ToolCall("read_capture", {"capture_id": created["id"]}),
        ]

    planner = ScriptedPlanner(steps())
    bound = planner.decide

    def decide(observation, deadline, current):
        clock.advance(6)
        return bound(observation, deadline, current)

    planner.decide = decide
    loop = ReadOnlyToolLoop(store, planner, clock=clock)
    result = loop.run(TOKEN, _fields(), _budget())
    assert result.status == "provider_timeout"
    assert result.reason == "time"
    assert result.text == ""
    assert result.tools_executed == 0


def test_citation_outside_the_tool_evidence_fails(tmp_path, encrypted_store_factory):
    _open_session()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = create_capture(store, "owner", "so este trecho", NOW)
    fact = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "fato de outro dominio logico", "owner_confirmation", "owner-note", NOW,
    )
    _planner, loop = _loop(store, [
        ToolCall("read_capture", {"capture_id": created["id"]}),
        FinalAnswer("fato de outro dominio logico", (fact["id"],)),
    ])
    result = loop.run(TOKEN, _fields(), _budget())
    assert result.status == "citation_rejected"
    assert result.reason == "not_evidence"
    assert result.text == ""
    assert result.tools_executed == 1


def test_other_domain_does_not_read_the_fact(tmp_path, encrypted_store_factory):
    _open_session()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    fact = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "fato do dominio a", "owner_confirmation", "owner-note", NOW,
    )
    _planner, loop = _loop(store, [
        ToolCall("read_confirmed_fact", {"record_id": fact["id"]}),
        FinalAnswer("fato do dominio a", (fact["id"],)),
    ])
    result = loop.run(TOKEN, _fields(domain_id="dom_synthetic_b"), _budget())
    assert result.status == "citation_rejected"
    assert result.text == ""


def test_body_over_2048_bytes_is_not_published():
    source_id = "ab" * 16
    huge = "x" * 3000
    body = encoded_tool_loop_body(
        status="evidence", cost="unmeasured", text=huge, source_ids=(source_id,),
    )
    assert len(body) > APP_RESPONSE_MAX_BYTES
    assert APP_RESPONSE_MAX_BYTES == 2048
    from read_only_tool_loop import _conclude

    result = _conclude(FinalAnswer(huge, (source_id,)), {source_id: huge}, 1)
    assert result.status == "response_too_large"
    assert result.text == ""
    assert result.cost == "unmeasured"


def test_module_has_no_network_or_effect_client():
    source = Path(__file__).with_name("read_only_tool_loop.py").read_text(encoding="utf-8")
    for needle in ("subprocess", "socket", "urlopen", "send_message", "pay"):
        assert needle not in source
