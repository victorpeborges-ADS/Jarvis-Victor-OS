"""Transições do gateway de conversa. O provider é falso e não sai da máquina."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from conversation_gateway import (
    APP_RESPONSE_MAX_BYTES,
    Budget,
    ConversationGateway,
    FakeProvider,
    ManualClock,
    ProviderCall,
    ProviderCancelled,
    ProviderContextLimit,
    ProviderFailed,
    ProviderOutput,
    ProviderTimeout,
)
from local_security import _session_by_token, put_session_for_tests, reset_state
from native_runtime import APP_PATHS

TOKEN = "sessao-sintetica"
OTHER = "sessao-seguinte"


def _budget(**overrides: object) -> Budget:
    values = {
        "max_seconds": 5,
        "max_tokens": 32,
        "max_attempts": 3,
        "max_calls": 4,
        "max_identical": 3,
    }
    values.update(overrides)
    return Budget(**values)


def _fields(**overrides: object) -> dict[str, object]:
    values = {
        "conversation_id": "conversa-a",
        "text": "ideia sintetica",
        "context_tokens": 1,
    }
    values.update(overrides)
    return values


def _reply(text: str = "resposta sintetica", **overrides: object) -> ProviderOutput:
    values = {"text": text, "output_tokens": 1, "cost": "unmeasured", "repeat": False}
    values.update(overrides)
    return ProviderOutput(**values)


def _gateway(behavior, clock=None) -> tuple[FakeProvider, ConversationGateway]:
    provider = FakeProvider(behavior)
    return provider, ConversationGateway(provider, clock=clock)


@pytest.fixture
def session():
    reset_state()
    put_session_for_tests(TOKEN, "owner", "csrf-sintetico")
    yield TOKEN
    reset_state()


def test_fake_reply_is_deterministic_and_cost_is_not_zero(session):
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply())
    first = gateway.run(session, _fields(), _budget())
    second = gateway.run(session, _fields(), _budget())
    assert (first.status, first.text, first.cost, first.provider_id, first.calls) == (
        second.status, second.text, second.cost, second.provider_id, second.calls,
    )
    assert first.generation == 1
    assert second.generation == 2
    assert first.status == "completed"
    assert first.text == "resposta sintetica"
    assert first.cost == "unmeasured"
    assert first.cost != "0"
    assert first.provider_id == "fake-deterministic"
    assert provider.invocations == 2
    assert gateway.visible_text(session, "conversa-a") == "resposta sintetica"
    assert TOKEN not in repr(ProviderCall(1, "conversa-a", "ideia sintetica", 1, 1))


def test_provider_is_not_given_the_session_token(session):
    seen: list[ProviderCall] = []

    def behavior(call, cancel, deadline, clock):
        seen.append(call)
        return _reply()

    _provider, gateway = _gateway(behavior)
    gateway.run(session, _fields(), _budget())
    assert seen[0].conversation_id == "conversa-a"
    assert TOKEN not in repr(seen[0])


def test_another_provider_class_uses_the_same_gateway(session):
    class OtherFake:
        provider_id = "other-fake"

        def complete(self, call, cancel, deadline, clock):
            return _reply("outro falso")

    result = ConversationGateway(OtherFake()).run(session, _fields(), _budget())
    assert result.status == "completed"
    assert result.provider_id == "other-fake"
    assert result.text == "outro falso"


def test_non_retryable_failure_is_terminal_and_hides_text(session):
    def behavior(call, cancel, deadline, clock):
        raise ProviderFailed(retryable=False)

    provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget())
    assert result.status == "provider_failed"
    assert result.text == ""
    assert result.calls == 1
    assert provider.invocations == 1
    assert gateway.visible_text(session, "conversa-a") == ""


def test_retryable_failure_then_success_stays_inside_attempt_budget(session):
    state = {"calls": 0}

    def behavior(call, cancel, deadline, clock):
        state["calls"] += 1
        if state["calls"] == 1:
            raise ProviderFailed(retryable=True)
        return _reply("na segunda")

    _provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget(max_attempts=2))
    assert result.status == "completed"
    assert result.text == "na segunda"
    assert result.calls == 2


def test_retryable_failures_stop_when_attempts_end(session):
    def behavior(call, cancel, deadline, clock):
        raise ProviderFailed(retryable=True)

    provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget(max_attempts=2, max_calls=4, max_identical=4))
    assert result.status == "budget_exhausted"
    assert result.reason == "attempts"
    assert result.text == ""
    assert result.calls == 2
    assert provider.invocations == 2


def test_timeout_discards_the_late_body(session):
    clock = ManualClock()

    def behavior(call, cancel, deadline, clock):
        clock.advance(5)
        return _reply("tarde")

    provider, gateway = _gateway(behavior, clock)
    result = gateway.run(session, _fields(), _budget(max_seconds=1))
    assert result.status == "provider_timeout"
    assert result.reason == "time"
    assert result.text == ""
    assert provider.invocations == 1
    assert gateway.visible_text(session, "conversa-a") == ""


def test_provider_timeout_signal_is_terminal(session):
    def behavior(call, cancel, deadline, clock):
        raise ProviderTimeout()

    provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget())
    assert result.status == "provider_timeout"
    assert result.text == ""
    assert provider.invocations == 1


def test_repeat_after_deadline_does_not_start_another_call(session):
    clock = ManualClock()

    def behavior(call, cancel, deadline, clock):
        clock.advance(5)
        return _reply("de novo", repeat=True)

    provider, gateway = _gateway(behavior, clock)
    result = gateway.run(session, _fields(), _budget(max_seconds=1, max_calls=4, max_identical=4))
    assert result.status == "budget_exhausted"
    assert result.reason == "time"
    assert result.calls == 1
    assert provider.invocations == 1


def test_context_over_budget_does_not_call_or_erase_the_previous_reply(session):
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply("primeira"))
    assert gateway.run(session, _fields(), _budget()).status == "completed"
    blocked = gateway.run(session, _fields(context_tokens=9), _budget(max_tokens=4))
    assert blocked.status == "context_limit"
    assert blocked.reason == "context"
    assert blocked.calls == 0
    assert provider.invocations == 1
    assert gateway.visible_text(session, "conversa-a") == "primeira"


def test_provider_can_signal_context_limit(session):
    def behavior(call, cancel, deadline, clock):
        raise ProviderContextLimit()

    provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget())
    assert result.status == "context_limit"
    assert result.text == ""
    assert provider.invocations == 1


def test_output_tokens_over_budget_discard_the_body(session):
    provider, gateway = _gateway(
        lambda call, cancel, deadline, clock: _reply("excedeu", output_tokens=4)
    )
    result = gateway.run(session, _fields(context_tokens=1), _budget(max_tokens=4))
    assert result.status == "budget_exhausted"
    assert result.reason == "tokens"
    assert result.text == ""
    assert provider.invocations == 1
    assert gateway.visible_text(session, "conversa-a") == ""


def test_identical_loop_stops_before_another_call(session):
    def behavior(call, cancel, deadline, clock):
        return _reply("de novo", repeat=True)

    provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget(max_identical=2, max_calls=8, max_attempts=8))
    assert result.status == "loop_detected"
    assert result.reason == "identical"
    assert result.calls == 2
    assert provider.invocations == 2


def test_call_limit_stops_a_repeat_that_is_still_inside_the_loop_ceiling(session):
    def behavior(call, cancel, deadline, clock):
        return _reply("de novo", repeat=True)

    provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget(max_calls=2, max_identical=5, max_attempts=5))
    assert result.status == "call_limit"
    assert result.reason == "calls"
    assert result.calls == 2
    assert provider.invocations == 2


def test_cancel_near_completion_drops_the_body(session):
    entered, release = threading.Event(), threading.Event()
    saw_cancel = {"value": False}

    def behavior(call, cancel, deadline, clock):
        entered.set()
        assert release.wait(2)
        saw_cancel["value"] = cancel.is_set()
        return _reply("quase pronta")

    provider, gateway = _gateway(behavior)
    holder: dict[str, object] = {}

    def run():
        holder["result"] = gateway.run(session, _fields(), _budget())

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        gateway.cancel(session, "conversa-a")
    finally:
        release.set()
    worker.join(2)
    assert not worker.is_alive()
    result = holder["result"]
    assert saw_cancel["value"] is True
    assert result.status == "cancelled"
    assert result.text == ""
    assert provider.invocations == 1
    assert gateway.visible_text(session, "conversa-a") == ""


def test_provider_cooperative_cancel_is_terminal(session):
    entered, release = threading.Event(), threading.Event()

    def behavior(call, cancel, deadline, clock):
        entered.set()
        assert release.wait(2)
        if cancel.is_set():
            raise ProviderCancelled()
        return _reply("nao devia")

    _provider, gateway = _gateway(behavior)
    holder: dict[str, object] = {}

    def run():
        holder["result"] = gateway.run(session, _fields(), _budget())

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        gateway.cancel(session, "conversa-a")
    finally:
        release.set()
    worker.join(2)
    assert holder["result"].status == "cancelled"
    assert holder["result"].text == ""


def test_switch_discards_a_late_body_and_keeps_the_new_reply(session):
    entered, release = threading.Event(), threading.Event()

    def behavior(call, cancel, deadline, clock):
        if call.generation == 1:
            entered.set()
            assert release.wait(2)
            return _reply("velho")
        return _reply("novo")

    _provider, gateway = _gateway(behavior)
    holder: dict[str, object] = {}

    def run():
        holder["old"] = gateway.run(session, _fields(), _budget())

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        assert gateway.switch(session, "conversa-a") is True
        assert gateway.visible_text(session, "conversa-a") == ""
        fresh = gateway.run(session, _fields(), _budget())
    finally:
        release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert holder["old"].status == "stale_session"
    assert holder["old"].reason == "generation"
    assert holder["old"].text == ""
    assert fresh.status == "completed"
    assert fresh.text == "novo"
    assert gateway.visible_text(session, "conversa-a") == "novo"


def test_closed_session_discards_a_late_body(session):
    entered, release = threading.Event(), threading.Event()

    def behavior(call, cancel, deadline, clock):
        entered.set()
        assert release.wait(2)
        return _reply("atrasada")

    _provider, gateway = _gateway(behavior)
    holder: dict[str, object] = {}

    def run():
        holder["old"] = gateway.run(session, _fields(), _budget())

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        gateway.end_session(session)
        with pytest.raises(HTTPException):
            _session_by_token(session)
    finally:
        release.set()
    worker.join(2)
    assert holder["old"].status == "stale_session"
    assert holder["old"].reason == "closed"
    assert holder["old"].text == ""
    assert gateway.visible_text(session, "conversa-a") == ""
    put_session_for_tests(OTHER, "owner", "csrf-seguinte")
    provider = FakeProvider(lambda call, cancel, deadline, clock: _reply("da sessao nova"))
    gateway._provider = provider
    fresh = gateway.run(OTHER, _fields(), _budget())
    assert fresh.status == "completed"
    assert fresh.text == "da sessao nova"
    assert "atrasada" not in fresh.text
    assert gateway.visible_text(session, "conversa-a") == ""


def test_a_retired_token_cannot_run_again(session):
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply())
    gateway.end_session(session)
    put_session_for_tests(TOKEN, "owner", "csrf-sintetico")
    result = gateway.run(session, _fields(), _budget())
    assert result.status == "session_required"
    assert provider.invocations == 0


def test_second_turn_supersedes_an_older_inflight_reply(session):
    entered, release = threading.Event(), threading.Event()

    def behavior(call, cancel, deadline, clock):
        if call.generation == 1:
            entered.set()
            assert release.wait(2)
            return _reply("velho")
        return _reply("atual")

    _provider, gateway = _gateway(behavior)
    holder: dict[str, object] = {}

    def run():
        holder["old"] = gateway.run(session, _fields(), _budget())

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        current = gateway.run(session, _fields(), _budget())
    finally:
        release.set()
    worker.join(2)
    assert holder["old"].status == "stale_session"
    assert holder["old"].text == ""
    assert current.status == "completed"
    assert current.text == "atual"
    assert gateway.visible_text(session, "conversa-a") == "atual"


def test_extra_field_is_rejected_without_a_call(session):
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply("primeira"))
    gateway.run(session, _fields(), _budget())
    rejected = gateway.run(session, _fields(extra="nao"), _budget())
    assert rejected.status == "invalid_request"
    assert rejected.reason == "fields"
    assert provider.invocations == 1
    assert gateway.visible_text(session, "conversa-a") == "primeira"


def test_unexpected_provider_error_does_not_return_its_message(session):
    def behavior(call, cancel, deadline, clock):
        raise RuntimeError("texto secreto do usuario")

    _provider, gateway = _gateway(behavior)
    result = gateway.run(session, _fields(), _budget())
    assert result.status == "provider_failed"
    assert result.text == ""
    assert "secreto" not in result.reason
    assert "secreto" not in result.text


def test_unknown_cost_stays_unmeasured(session):
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply(cost="talvez"))
    result = gateway.run(session, _fields(), _budget())
    assert result.status == "completed"
    assert result.cost == "unmeasured"
    assert result.cost != "0"
    assert provider.invocations == 1


def test_response_over_the_application_body_limit_is_not_stored(session):
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply("a" * 2100))
    result = gateway.run(session, _fields(), _budget(max_tokens=4096))
    assert APP_RESPONSE_MAX_BYTES == 2048
    assert result.status == "response_too_large"
    assert result.text == ""
    assert provider.invocations == 1
    assert gateway.visible_text(session, "conversa-a") == ""


def test_closed_session_never_reaches_the_provider():
    reset_state()
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply())
    result = gateway.run(TOKEN, _fields(), _budget())
    assert result.status == "session_required"
    assert provider.invocations == 0


def test_gateway_does_not_open_a_route_or_a_network_client():
    source = Path(__file__).with_name("conversation_gateway.py").read_text(encoding="utf-8")
    for banned in ("httpx", "requests", "openai", "socket", "urllib.request", "http.client"):
        assert banned not in source
    assert ("POST", "/v1/app/conversation/ask") in APP_PATHS


def test_switch_without_a_session_does_not_call_the_provider():
    reset_state()
    provider, gateway = _gateway(lambda call, cancel, deadline, clock: _reply())
    assert gateway.switch(TOKEN, "conversa-a") is False
    assert provider.invocations == 0
