"""Loop de leitura do provider falso.

O catálogo só lê captura explícita ou fato confirmado no domínio pedido.
Ferramenta desconhecida, campo extra, repetição e prazo encerram o turno.
Não há escrita, rede nem efeito externo. Custo desconhecido permanece
`unmeasured`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping
from urllib.parse import quote

from conversation_gateway import APP_RESPONSE_MAX_BYTES, Budget, ProviderTimeout
from local_security import native_session_confirmed
from memory_categories import DOMAINS
from memory_store import SQLiteMemoryStore
from artifact_store import read_verified_artifact

_OUTER = frozenset({"conversation_id", "question", "domain_id"})
_TOOLS = {
    "read_capture": "capture_id",
    "read_confirmed_fact": "record_id",
    "read_authorized_document": "document_id",
}
_CONVERSATION_ID = re.compile(r"[a-z0-9_-]{1,32}\Z")
_QUESTION = re.compile(r"[^\x00-\x1f\x7f]{1,400}\Z")
_RECORD_ID = re.compile(r"[0-9a-f]{32}\Z")
_DOCUMENT_ID = re.compile(r"(?:[0-9a-f]{32}|doc_[0-9a-f]{16}|[a-z0-9_-]{1,32})\Z")


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, str]


@dataclass(frozen=True)
class FinalAnswer:
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ToolLoopResult:
    status: str
    reason: str
    text: str
    source_ids: tuple[str, ...]
    tools_executed: int
    cost: str


class ScriptedPlanner:
    """Entrega passos já escritos. Não escolhe ferramenta por conta própria."""

    def __init__(self, steps: list[ToolCall | FinalAnswer]) -> None:
        self._steps = list(steps)
        self.invocations = 0

    def decide(self, observation: str, deadline: float, clock) -> ToolCall | FinalAnswer:
        self.invocations += 1
        if clock() >= deadline:
            raise ProviderTimeout
        if not self._steps:
            return FinalAnswer(text="", source_ids=())
        return self._steps.pop(0)


def encoded_tool_loop_body(*, status: str, cost: str, text: str, source_ids: tuple[str, ...]) -> bytes:
    pairs = (
        ("ok", "true" if status == "evidence" else "false"),
        ("status", status),
        ("cost", cost),
        ("text", text),
        ("sources", ",".join(source_ids)),
    )
    return "".join(f"{name}={quote(value, safe='-_.~')}\n" for name, value in pairs).encode("ascii")


class ReadOnlyToolLoop:
    def __init__(
        self,
        store: SQLiteMemoryStore,
        planner: ScriptedPlanner,
        *,
        clock,
        manifest_sha256: str = "",
        now: datetime | None = None,
        authorized_documents: Mapping[str, str] | None = None,
    ) -> None:
        self._store = store
        self._planner = planner
        self._clock = clock
        self._manifest_sha256 = manifest_sha256
        self._now = now or datetime.now(timezone.utc)
        self._authorized_documents = dict(authorized_documents or {})

    def run(self, session_token: str, fields: Mapping[str, object], budget: Budget) -> ToolLoopResult:
        empty = ToolLoopResult("invalid_request", "fields", "", (), 0, "unmeasured")
        if set(fields) != _OUTER:
            return empty
        if not _text(fields.get("conversation_id"), _CONVERSATION_ID):
            return empty
        if not _text(fields.get("question"), _QUESTION) or fields.get("domain_id") not in DOMAINS:
            return empty
        if not _session_open(session_token):
            return ToolLoopResult("session_required", "closed", "", (), 0, "unmeasured")
        domain_id = str(fields["domain_id"])
        deadline = self._clock() + budget.max_seconds
        evidence: dict[str, str] = {}
        seen: set[tuple[str, str]] = set()
        executed = 0
        decisions = 0
        observation = ""
        while True:
            if self._clock() >= deadline:
                return ToolLoopResult("provider_timeout", "time", "", (), executed, "unmeasured")
            try:
                decisions += 1
                if decisions > budget.max_calls + 1:
                    return ToolLoopResult("call_limit", "calls", "", (), executed, "unmeasured")
                step = self._planner.decide(observation, deadline, self._clock)
            except ProviderTimeout:
                return ToolLoopResult("provider_timeout", "time", "", (), executed, "unmeasured")
            if self._clock() >= deadline:
                return ToolLoopResult("provider_timeout", "time", "", (), executed, "unmeasured")
            if isinstance(step, ToolCall):
                if executed >= budget.max_calls:
                    return ToolLoopResult("call_limit", "calls", "", (), executed, "unmeasured")
                outcome = self._tool(step, domain_id, seen)
                if isinstance(outcome, ToolLoopResult):
                    return ToolLoopResult(
                        outcome.status, outcome.reason, "", (), executed, "unmeasured",
                    )
                seen.add(outcome[0])
                evidence[outcome[1]] = outcome[2]
                observation = outcome[2]
                executed += 1
                continue
            if not isinstance(step, FinalAnswer):
                return ToolLoopResult("provider_failed", "", "", (), executed, "unmeasured")
            return _conclude(step, evidence, executed)

    def _tool(
        self,
        call: ToolCall,
        domain_id: str,
        seen: set[tuple[str, str]],
    ) -> ToolLoopResult | tuple[tuple[str, str], str, str]:
        spec = _TOOLS.get(call.name)
        if spec is None or not isinstance(call.arguments, Mapping):
            return ToolLoopResult("unknown_tool", call.name if isinstance(call.name, str) else "", "", (), 0, "unmeasured")
        argument = spec
        if set(call.arguments) != {argument}:
            return ToolLoopResult("invalid_request", "extra_field", "", (), 0, "unmeasured")
        record_id = call.arguments.get(argument)
        identifier_pattern = _DOCUMENT_ID if call.name == "read_authorized_document" else _RECORD_ID
        if not _text(record_id, identifier_pattern):
            return ToolLoopResult("invalid_request", "fields", "", (), 0, "unmeasured")
        key = (call.name, record_id)
        if key in seen:
            return ToolLoopResult("loop_detected", "identical", "", (), 0, "unmeasured")
        if call.name == "read_authorized_document":
            static_document = self._authorized_documents.get(record_id)
            if static_document is not None:
                snippet = static_document
            elif _text(record_id, _RECORD_ID):
                verified = read_verified_artifact(
                    self._store,
                    "owner",
                    domain_id,
                    record_id,
                    self._manifest_sha256,
                    self._now,
                )
                snippet = verified["text"] if verified else ""
            else:
                snippet = ""
        else:
            table = "local_captures" if call.name == "read_capture" else "confirmed_facts"
            with self._store.transaction() as connection:
                row = connection.execute(
                    f"SELECT body FROM {table} WHERE id = ? AND owner = ? AND domain_id = ?",
                    (record_id, "owner", domain_id),
                ).fetchone()
            snippet = row[0] if row is not None and isinstance(row[0], str) else ""
        return key, record_id, snippet


def _conclude(answer: FinalAnswer, evidence: dict[str, str], executed: int) -> ToolLoopResult:
    if not answer.source_ids and answer.text == "":
        return ToolLoopResult("insufficient_basis", "no_snippet", "", (), executed, "unmeasured")
    snippets = []
    for source_id in answer.source_ids:
        source_text = evidence.get(source_id)
        if source_text is None or source_text == "":
            return ToolLoopResult("citation_rejected", "not_evidence", "", (), executed, "unmeasured")
        snippets.append(source_text)
    claims = answer.text.split(" | ")
    if (
        len(claims) != len(snippets)
        or not all(claim and _present_verbatim(claim, source) for claim, source in zip(claims, snippets))
    ):
        return ToolLoopResult("citation_rejected", "not_evidence", "", (), executed, "unmeasured")
    text = answer.text
    body = encoded_tool_loop_body(
        status="evidence", cost="unmeasured", text=text, source_ids=answer.source_ids,
    )
    if len(body) > APP_RESPONSE_MAX_BYTES:
        return ToolLoopResult("response_too_large", "", "", (), executed, "unmeasured")
    return ToolLoopResult("evidence", "", text, answer.source_ids, executed, "unmeasured")


def _present_verbatim(claim: str, source: str) -> bool:
    start = 0
    while True:
        index = source.find(claim, start)
        if index < 0:
            return False
        end = index + len(claim)
        left_ok = index == 0 or not source[index - 1].isalnum() or not claim[0].isalnum()
        right_ok = end == len(source) or not source[end].isalnum() or not claim[-1].isalnum()
        if left_ok and right_ok:
            return True
        start = index + 1


def _text(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _session_open(session_token: str) -> bool:
    try:
        with native_session_confirmed(session_token) as session:
            return session.principal == "owner"
    except PermissionError:
        return False
