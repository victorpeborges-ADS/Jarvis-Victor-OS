"""Contrato de conversa sem provider real.

O adapter incluído é determinístico e não abre rede. Ele prova transições do
gateway. Não prova que um texto seja verdadeiro, útil ou fundamentado.

O id de conversa deste módulo é só a chave volátil do turno. Não fecha a
decisão de retenção, autor, exportação ou sincronização.
"""

from __future__ import annotations

import math
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol
from urllib.parse import quote

from fastapi import HTTPException

from local_security import _close_session_for, _session_by_token, native_session_confirmed
from native_runtime import APP_RESPONSE_MAX_BYTES

_CONVERSATION_ID = re.compile(r"[a-z0-9_-]{1,32}\Z")
_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,400}\Z")
_OUTPUT_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,4096}\Z")
_PROVIDER_ID = re.compile(r"[a-z0-9-]{1,40}\Z")
_MEASURED_COST = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?\Z")
_TURN_FIELDS = frozenset({"conversation_id", "text", "context_tokens"})


class ProviderFailed(Exception):
    def __init__(self, *, retryable: bool) -> None:
        super().__init__("provider_failed")
        self.retryable = retryable


class ProviderTimeout(Exception):
    def __init__(self) -> None:
        super().__init__("provider_timeout")


class ProviderCancelled(Exception):
    def __init__(self) -> None:
        super().__init__("cancelled")


class ProviderContextLimit(Exception):
    def __init__(self) -> None:
        super().__init__("context_limit")


@dataclass(frozen=True)
class Budget:
    max_seconds: float
    max_tokens: int
    max_attempts: int
    max_calls: int
    max_identical: int


@dataclass(frozen=True)
class ProviderCall:
    generation: int
    conversation_id: str
    text: str
    context_tokens: int
    attempt: int


@dataclass(frozen=True)
class ProviderOutput:
    text: str
    output_tokens: int
    cost: str
    repeat: bool


class ConversationProvider(Protocol):
    provider_id: str

    def complete(
        self,
        call: ProviderCall,
        cancel: threading.Event,
        deadline: float,
        clock: Callable[[], float],
    ) -> ProviderOutput:
        """Uma chamada. O cancelamento é cooperativo: o provider observa o evento."""


class FakeProvider:
    """Executor de um comportamento injetado. Não tem URL, chave nem relógio de rede."""

    provider_id = "fake-deterministic"

    def __init__(self, behavior: Callable[..., ProviderOutput]) -> None:
        self._behavior = behavior
        self.invocations = 0
        self._count_lock = threading.Lock()

    def complete(
        self,
        call: ProviderCall,
        cancel: threading.Event,
        deadline: float,
        clock: Callable[[], float],
    ) -> ProviderOutput:
        with self._count_lock:
            self.invocations += 1
        return self._behavior(call, cancel, deadline, clock)


@dataclass(frozen=True)
class TurnResult:
    status: str
    reason: str
    text: str
    provider_id: str
    cost: str
    calls: int
    generation: int


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def encoded_turn_body(*, status: str, provider_id: str, cost: str, text: str) -> bytes:
    ok = "true" if status == "completed" else "false"
    pairs = (
        ("ok", ok),
        ("status", status),
        ("provider_id", provider_id),
        ("cost", cost),
        ("text", text),
    )
    return "".join(f"{name}={quote(value, safe='-_.~')}\n" for name, value in pairs).encode("ascii")


def _plain(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _whole(value: object, *, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _normalize_cost(value: object) -> str:
    if value == "unmeasured":
        return "unmeasured"
    if isinstance(value, str) and _MEASURED_COST.fullmatch(value) is not None:
        return value
    return "unmeasured"


class ConversationGateway:
    def __init__(self, provider: ConversationProvider, *, clock: Callable[[], float] | None = None) -> None:
        self._provider = provider
        self._clock = clock or _monotonic
        self._lock = threading.Lock()
        self._generation: dict[tuple[str, str], int] = {}
        self._visible: dict[tuple[str, str], str] = {}
        self._inflight: dict[str, tuple[tuple[str, str], int, threading.Event]] = {}
        self._closed: set[str] = set()

    def visible_text(self, session_token: str, conversation_id: str) -> str:
        with self._lock:
            return self._visible.get((session_token, conversation_id), "")

    def cancel(self, session_token: str, conversation_id: str) -> None:
        key = (session_token, conversation_id)
        with self._lock:
            for inflight_key, _generation, event in self._inflight.values():
                if inflight_key == key:
                    event.set()

    def retire_session(self, session_token: str) -> None:
        """Forget transient turns and cancel in-flight work after session close."""
        with self._lock:
            self._retire_locked(session_token)

    def clear_all(self) -> None:
        """Cancel volatile work at storage lock or runtime shutdown."""
        with self._lock:
            tokens = {key[0] for key in self._generation}
            tokens.update(key[0] for key, _generation, _event in self._inflight.values())
            for token in tokens:
                self._retire_locked(token)
            self._visible.clear()
            self._generation.clear()
            self._closed.clear()

    def switch(self, session_token: str, conversation_id: str) -> bool:
        if not self._session_open(session_token):
            return False
        with self._lock:
            if session_token in self._closed:
                return False
            self._bump_locked((session_token, conversation_id))
        return True

    def end_session(self, session_token: str) -> None:
        with self._lock:
            self._retire_locked(session_token)
        try:
            session = _session_by_token(session_token)
        except HTTPException:
            return
        _close_session_for(session)

    def run(
        self,
        session_token: str,
        fields: Mapping[str, object],
        budget: Budget,
        *,
        cancel_event: threading.Event | None = None,
    ) -> TurnResult:
        provider_id = self._provider_id()
        invalid = _invalid_turn(fields, budget)
        if invalid is not None:
            return _result(provider_id, status="invalid_request", reason=invalid)
        assert isinstance(fields["conversation_id"], str)
        assert isinstance(fields["text"], str)
        assert isinstance(fields["context_tokens"], int)
        if not self._session_open(session_token):
            return _result(provider_id, status="session_required", reason="closed")
        if fields["context_tokens"] > budget.max_tokens:
            return _result(provider_id, status="context_limit", reason="context")
        key = (session_token, fields["conversation_id"])
        with self._lock:
            if session_token in self._closed or not self._session_open(session_token):
                return _result(provider_id, status="session_required", reason="closed")
            generation = self._bump_locked(key)
            cancel = cancel_event or threading.Event()
            turn_id = secrets.token_hex(8)
            self._inflight[turn_id] = (key, generation, cancel)
        try:
            return self._drive(
                session_token=session_token,
                key=key,
                generation=generation,
                text=fields["text"],
                context_tokens=fields["context_tokens"],
                budget=budget,
                cancel=cancel,
                provider_id=provider_id,
            )
        finally:
            with self._lock:
                self._inflight.pop(turn_id, None)

    def _drive(
        self,
        *,
        session_token: str,
        key: tuple[str, str],
        generation: int,
        text: str,
        context_tokens: int,
        budget: Budget,
        cancel: threading.Event,
        provider_id: str,
    ) -> TurnResult:
        deadline = self._clock() + budget.max_seconds
        calls = 0
        identical_returns = 0
        while True:
            if cancel.is_set():
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="cancelled", reason="", text="", cost="unmeasured", calls=calls,
                )
            if calls > 0 and self._clock() >= deadline:
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="budget_exhausted", reason="time", text="", cost="unmeasured", calls=calls,
                )
            if identical_returns >= budget.max_identical:
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="loop_detected", reason="identical", text="", cost="unmeasured", calls=calls,
                )
            if calls >= budget.max_calls:
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="call_limit", reason="calls", text="", cost="unmeasured", calls=calls,
                )
            if calls >= budget.max_attempts:
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="budget_exhausted", reason="attempts", text="", cost="unmeasured", calls=calls,
                )
            call = ProviderCall(
                generation=generation,
                conversation_id=key[1],
                text=text,
                context_tokens=context_tokens,
                attempt=calls + 1,
            )
            try:
                output = self._provider.complete(call, cancel, deadline, self._clock)
            except ProviderContextLimit:
                calls += 1
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="context_limit", reason="context", text="", cost="unmeasured", calls=calls,
                )
            except ProviderFailed as exc:
                calls += 1
                if self._clock() >= deadline:
                    return self._finish(
                        session_token, key, generation, cancel, provider_id,
                        status="budget_exhausted", reason="time", text="", cost="unmeasured", calls=calls,
                    )
                if (
                    exc.retryable
                    and calls < budget.max_attempts
                    and calls < budget.max_calls
                    and not cancel.is_set()
                ):
                    continue
                status = "budget_exhausted" if exc.retryable else "provider_failed"
                reason = "attempts" if exc.retryable else ""
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status=status, reason=reason, text="", cost="unmeasured", calls=calls,
                )
            except ProviderTimeout:
                calls += 1
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="provider_timeout", reason="time", text="", cost="unmeasured", calls=calls,
                )
            except ProviderCancelled:
                calls += 1
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="cancelled", reason="", text="", cost="unmeasured", calls=calls,
                )
            except Exception:
                calls += 1
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="provider_failed", reason="", text="", cost="unmeasured", calls=calls,
                )
            calls += 1
            if not isinstance(output, ProviderOutput) or _output_rejected(output):
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="provider_failed", reason="", text="", cost="unmeasured", calls=calls,
                )
            if self._clock() >= deadline:
                late_status = "budget_exhausted" if output.repeat else "provider_timeout"
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status=late_status, reason="time", text="", cost="unmeasured", calls=calls,
                )
            cost = _normalize_cost(output.cost)
            if context_tokens + output.output_tokens > budget.max_tokens:
                return self._finish(
                    session_token, key, generation, cancel, provider_id,
                    status="budget_exhausted", reason="tokens", text="", cost=cost, calls=calls,
                )
            if output.repeat:
                identical_returns += 1
                continue
            return self._finish(
                session_token, key, generation, cancel, provider_id,
                status="completed", reason="", text=output.text, cost=cost, calls=calls,
            )

    def _finish(
        self,
        session_token: str,
        key: tuple[str, str],
        generation: int,
        cancel: threading.Event,
        provider_id: str,
        *,
        status: str,
        reason: str,
        text: str,
        cost: str,
        calls: int,
    ) -> TurnResult:
        with self._lock:
            stale = self._staleness_locked(session_token, key, generation)
            if stale:
                status, reason, text = "stale_session", stale, ""
            elif cancel.is_set():
                status, reason, text = "cancelled", "", ""
            if status == "completed":
                body = encoded_turn_body(status=status, provider_id=provider_id, cost=cost, text=text)
                if len(body) > APP_RESPONSE_MAX_BYTES:
                    status, text, cost = "response_too_large", "", "unmeasured"
                else:
                    self._visible[key] = text
            return _result(
                provider_id,
                status=status,
                reason=reason,
                text=text,
                cost=cost,
                calls=calls,
                generation=generation,
            )

    def _staleness_locked(self, session_token: str, key: tuple[str, str], generation: int) -> str:
        if session_token in self._closed:
            return "closed"
        if self._generation.get(key) != generation:
            return "generation"
        if not self._session_open(session_token):
            self._closed.add(session_token)
            self._visible.pop(key, None)
            return "closed"
        return ""

    def _bump_locked(self, key: tuple[str, str]) -> int:
        generation = self._generation.get(key, 0) + 1
        self._generation[key] = generation
        self._visible.pop(key, None)
        for inflight_key, inflight_generation, event in self._inflight.values():
            if inflight_key == key and inflight_generation != generation:
                event.set()
        return generation

    def _retire_locked(self, session_token: str) -> None:
        self._closed.add(session_token)
        for key in list(self._generation):
            if key[0] == session_token:
                self._generation[key] += 1
                self._visible.pop(key, None)
        for inflight_key, _generation, event in self._inflight.values():
            if inflight_key[0] == session_token:
                event.set()

    def _provider_id(self) -> str:
        provider_id = getattr(self._provider, "provider_id", "")
        if _plain(provider_id, _PROVIDER_ID):
            return provider_id
        return "invalid"

    def _session_open(self, session_token: str) -> bool:
        try:
            with native_session_confirmed(session_token) as session:
                return session.principal == "owner"
        except PermissionError:
            return False


def _monotonic() -> float:
    import time

    return time.monotonic()


def _invalid_turn(fields: Mapping[str, object], budget: Budget) -> str | None:
    if set(fields) != _TURN_FIELDS:
        return "fields"
    if not _plain(fields["conversation_id"], _CONVERSATION_ID) or not _plain(fields["text"], _TEXT):
        return "fields"
    if not _whole(fields["context_tokens"], minimum=0):
        return "fields"
    if isinstance(budget.max_seconds, bool) or not isinstance(budget.max_seconds, (int, float)):
        return "fields"
    if not math.isfinite(float(budget.max_seconds)) or budget.max_seconds <= 0:
        return "fields"
    for name in ("max_tokens", "max_attempts", "max_calls", "max_identical"):
        if not _whole(getattr(budget, name), minimum=1):
            return "fields"
    return None


def _output_rejected(output: ProviderOutput) -> bool:
    if not _plain(output.text, _OUTPUT_TEXT):
        return True
    if not _whole(output.output_tokens, minimum=0):
        return True
    if not isinstance(output.repeat, bool):
        return True
    return False


def _result(
    provider_id: str,
    *,
    status: str,
    reason: str,
    text: str = "",
    cost: str = "unmeasured",
    calls: int = 0,
    generation: int = 0,
) -> TurnResult:
    return TurnResult(
        status=status,
        reason=reason,
        text=text,
        provider_id=provider_id,
        cost=cost,
        calls=calls,
        generation=generation,
    )
