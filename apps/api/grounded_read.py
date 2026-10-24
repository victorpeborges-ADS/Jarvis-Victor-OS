"""Leitura lexical fundamentada via ferramentas fechadas do servidor.

A evidência é um token presente na fonte, no recorte original. Sem esse
recorte o estado é base insuficiente e o texto visível fica vazio. O
provider falso só republica o recorte; não produz inferência.

O servidor escolhe as ferramentas de leitura. Conteúdo de fonte só é usado
como dado literal, nunca como instrução. Mensagens não são persistidas.
"""

from __future__ import annotations

import math
import re
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from urllib.parse import quote

from conversation_gateway import APP_RESPONSE_MAX_BYTES, Budget, ConversationGateway
from conversation_continuity import touch_conversation
from local_captures import _fold
from local_security import native_session_confirmed
from memory_categories import DOMAINS
from read_only_tool_loop import FinalAnswer, ReadOnlyToolLoop, ScriptedPlanner, ToolCall
from artifact_store import read_verified_artifact

DOMAIN_ID = "dom_synthetic_a"
MAX_CITATIONS = 3
MIN_TOKEN = 4
_FIELDS = frozenset({"conversation_id", "question", "domain_id"})
_CONVERSATION_ID = re.compile(r"[0-9a-f]{32}\Z")
_QUESTION = re.compile(r"[^\x00-\x1f\x7f]{1,400}\Z")
_DOC_ID = re.compile(r"[a-z0-9_-]{1,32}\Z")
_DOC_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,4096}\Z")


@dataclass(frozen=True)
class SyntheticDocument:
    id: str
    text: str
    domain_id: str
    authorized: bool


@dataclass(frozen=True)
class SourceCitation:
    id: str
    kind: str
    domain_id: str
    snippet: str


@dataclass(frozen=True)
class GroundedResult:
    status: str
    reason: str
    text: str
    sources: tuple[SourceCitation, ...]
    provider_calls: int
    latency_seconds: float
    omitted: int


def encoded_grounded_body(
    *,
    status: str,
    reason: str = "",
    provider_id: str,
    cost: str,
    text: str,
    omitted: int,
    sources: tuple[SourceCitation, ...],
) -> bytes:
    blob = "\n".join(
        "\t".join((item.id, item.kind, item.domain_id, item.snippet)) for item in sources
    )
    # `ok` means the closed request/response contract completed. Semantic
    # outcomes (for example insufficient_basis) live in `status`.
    ok = "true"
    pairs = (
        ("ok", ok),
        ("status", status),
        ("reason", reason),
        ("provider_id", provider_id),
        ("cost", cost),
        ("text", text),
        ("omitted", str(omitted)),
        ("sources", blob),
    )
    return "".join(f"{name}={quote(value, safe='-_.~')}\n" for name, value in pairs).encode("ascii")


class GroundedRead:
    def __init__(
        self,
        gateway: ConversationGateway,
        store,
        documents: tuple[SyntheticDocument, ...] | list[SyntheticDocument],
        publish: Callable[[str], None],
        *,
        manifest_sha256: str = "",
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._documents = tuple(documents)
        self._publish = publish
        self._manifest_sha256 = manifest_sha256
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._provider_id = getattr(gateway, "_provider").provider_id

    def ask(
        self,
        session_token: str,
        fields: Mapping[str, object],
        budget: Budget,
        *,
        cancel_event: threading.Event | None = None,
    ) -> GroundedResult:
        started = time.perf_counter()

        def finish(
            status: str,
            reason: str,
            *,
            text: str = "",
            sources: tuple[SourceCitation, ...] = (),
            provider_calls: int = 0,
            omitted: int = 0,
        ) -> GroundedResult:
            return GroundedResult(
                status=status,
                reason=reason,
                text=text,
                sources=sources,
                provider_calls=provider_calls,
                latency_seconds=time.perf_counter() - started,
                omitted=omitted,
            )

        if set(fields) != _FIELDS or not _plain(fields.get("conversation_id"), _CONVERSATION_ID):
            return finish("invalid_request", "fields")
        if not _plain(fields.get("question"), _QUESTION) or not _plain(fields.get("domain_id"), _DOC_ID):
            return finish("invalid_request", "fields")
        if not _budget_ok(budget):
            return finish("invalid_request", "fields")
        conversation_id = str(fields["conversation_id"])
        question = str(fields["question"])
        if not _session_open(session_token):
            return finish("session_required", "closed")
        if fields["domain_id"] not in DOMAINS or fields["domain_id"] != DOMAIN_ID:
            return finish("domain_rejected", "domain")
        now = self._now_fn()
        if touch_conversation(
            self._store, "owner", DOMAIN_ID, conversation_id, now,
        ) is None:
            self._gateway.switch(session_token, conversation_id)
            return finish("stale_session", "conversation")
        if cancel_event is not None and cancel_event.is_set():
            return finish("cancelled", "")

        wanted = _question_tokens(question)
        sources = self._search_sources(wanted, now)
        if cancel_event is not None and cancel_event.is_set():
            return finish("cancelled", "")
        matches = [item.citation for item in sources]
        if not matches:
            self._gateway.switch(session_token, conversation_id)
            return finish("insufficient_basis", "no_snippet")

        # The native budget is one closed read and one deterministic provider
        # call. Additional matching rows are counted but never read this turn.
        selected = sources[0]
        citations = (selected.citation,)
        omitted = len(sources) - 1
        text = " | ".join(item.snippet for item in citations)
        context_tokens = len(wanted)
        output_tokens = len(citations)
        provider_id = self._provider_id if isinstance(self._provider_id, str) else "invalid"
        body = encoded_grounded_body(
            status="evidence",
            reason="",
            provider_id=provider_id,
            cost="unmeasured",
            text=text,
            omitted=omitted,
            sources=citations,
        )
        if len(body) > APP_RESPONSE_MAX_BYTES:
            self._gateway.switch(session_token, conversation_id)
            return finish("response_too_large", "")
        if context_tokens + output_tokens > budget.max_tokens:
            self._gateway.switch(session_token, conversation_id)
            return finish("budget_exhausted", "tokens")

        planner = ScriptedPlanner([
            ToolCall(selected.tool_name, {selected.argument_name: selected.tool_id}),
            FinalAnswer(text, (selected.citation.id,)),
        ])
        loop = ReadOnlyToolLoop(
            self._store,
            planner,
            clock=time.monotonic,
            manifest_sha256=self._manifest_sha256,
            now=now,
            authorized_documents=selected.authorized_documents,
        )
        read = loop.run(
            session_token,
            {"conversation_id": conversation_id, "question": question, "domain_id": DOMAIN_ID},
            budget,
        )
        if cancel_event is not None and cancel_event.is_set():
            return finish("cancelled", "")
        if read.status != "evidence" or read.text != text or read.source_ids != (selected.citation.id,):
            self._gateway.switch(session_token, conversation_id)
            status = "insufficient_basis" if read.status in {"citation_rejected", "invalid_request"} else read.status
            return finish(status, read.reason)

        self._publish(text)
        turn = self._gateway.run(
            session_token,
            {
                "conversation_id": conversation_id,
                "text": question,
                "context_tokens": context_tokens,
            },
            budget,
            cancel_event=cancel_event,
        )
        if turn.status != "completed" or turn.text != text or not _quotes_are_evidence(citations, matches):
            self._gateway.switch(session_token, conversation_id)
            if turn.status != "completed":
                return finish(turn.status, turn.reason, provider_calls=turn.calls)
            return finish("insufficient_basis", "not_evidence", provider_calls=turn.calls)
        if self._gateway.visible_text(session_token, conversation_id) != text:
            return finish("insufficient_basis", "not_evidence", provider_calls=turn.calls)
        return finish(
            "evidence",
            "",
            text=text,
            sources=citations,
            provider_calls=turn.calls,
            omitted=omitted,
        )

    def _search_sources(self, wanted: tuple[str, ...], now: datetime) -> list["_ToolSource"]:
        sources: list[_ToolSource] = []
        with self._store.transaction() as connection:
            rows = connection.execute(
                """SELECT id, body, domain_id FROM local_captures
                   WHERE owner = ? AND domain_id = ?
                   ORDER BY id ASC""",
                ("owner", DOMAIN_ID),
            ).fetchall()
        for row in rows:
            if row[2] != DOMAIN_ID or not isinstance(row[0], str) or not isinstance(row[1], str):
                continue
            snippet = _snippet(row[1], wanted)
            if snippet is not None and snippet in row[1]:
                sources.append(_ToolSource(
                    SourceCitation(row[0], "capture", DOMAIN_ID, snippet),
                    row[1], "read_capture", "capture_id", row[0], {},
                ))
        with self._store.transaction() as connection:
            facts = connection.execute(
                """SELECT id, body, domain_id FROM confirmed_facts
                   WHERE owner=? AND domain_id=? ORDER BY id ASC""",
                ("owner", DOMAIN_ID),
            ).fetchall()
        for row in facts:
            if row[2] != DOMAIN_ID or not isinstance(row[0], str) or not isinstance(row[1], str):
                continue
            snippet = _snippet(row[1], wanted)
            if snippet is not None:
                sources.append(_ToolSource(
                    SourceCitation(row[0], "confirmed_fact", DOMAIN_ID, snippet),
                    row[1], "read_confirmed_fact", "record_id", row[0], {},
                ))
        for document in self._usable_documents():
            snippet = _snippet(document.text, wanted)
            if snippet is not None:
                sources.append(_ToolSource(
                    SourceCitation(document.id, "document", DOMAIN_ID, snippet),
                    document.text, "read_authorized_document", "document_id", document.id,
                    {document.id: document.text},
                ))
        if self._manifest_sha256:
            with self._store.transaction() as connection:
                artifact_rows = connection.execute(
                    """SELECT id FROM synthetic_artifacts WHERE owner=? AND domain_id=?
                       AND origin_id='generate-synthetic-document' AND version='1.0.0'
                       ORDER BY created_at DESC, id ASC""",
                    ("owner", DOMAIN_ID),
                ).fetchall()
            for (artifact_id,) in artifact_rows:
                verified = read_verified_artifact(
                    self._store, "owner", DOMAIN_ID, artifact_id,
                    self._manifest_sha256, now,
                )
                if verified is None:
                    continue
                snippet = _snippet(verified["text"], wanted)
                if snippet is not None:
                    sources.append(_ToolSource(
                        SourceCitation(artifact_id, "document", DOMAIN_ID, snippet),
                        verified["text"], "read_authorized_document", "document_id", artifact_id, {},
                    ))
        sources.sort(key=lambda item: (
            {"capture": 0, "confirmed_fact": 1, "document": 2}[item.citation.kind],
            item.citation.id,
        ))
        return sources

    def _usable_documents(self) -> list[SyntheticDocument]:
        usable = []
        seen: set[str] = set()
        for document in self._documents:
            if not isinstance(document, SyntheticDocument):
                continue
            if document.authorized is not True or document.domain_id != DOMAIN_ID:
                continue
            if not _plain(document.id, _DOC_ID) or not _plain(document.text, _DOC_TEXT):
                continue
            if document.id in seen:
                continue
            seen.add(document.id)
            usable.append(document)
        return usable


def _session_open(session_token: str) -> bool:
    try:
        with native_session_confirmed(session_token) as session:
            return session.principal == "owner"
    except PermissionError:
        return False


def _question_tokens(question: str) -> tuple[str, ...]:
    found: list[str] = []
    for start, end in _token_spans(question):
        folded = _fold(question[start:end])
        if len(folded) >= MIN_TOKEN and folded not in found:
            found.append(folded)
    return tuple(found)


def _snippet(text: str, wanted: tuple[str, ...]) -> str | None:
    accepted = set(wanted)
    for start, end in _token_spans(text):
        piece = text[start:end]
        if _fold(piece) in accepted:
            return piece
    return None


def _match_sources(
    captures: list[tuple[str, str]],
    documents: list[SyntheticDocument],
    wanted: tuple[str, ...],
) -> list[SourceCitation]:
    if not wanted:
        return []
    found: list[SourceCitation] = []
    for capture_id, body in captures:
        piece = _snippet(body, wanted)
        if piece is not None and piece in body:
            found.append(SourceCitation(capture_id, "capture", DOMAIN_ID, piece))
    for document in documents:
        piece = _snippet(document.text, wanted)
        if piece is not None and piece in document.text:
            found.append(SourceCitation(document.id, "document", DOMAIN_ID, piece))
    found.sort(key=lambda item: (0 if item.kind == "capture" else 1, item.id))
    return found


def _quotes_are_evidence(citations: tuple[SourceCitation, ...], matches: list[SourceCitation]) -> bool:
    by_id = {(item.kind, item.id): item for item in matches}
    for citation in citations:
        original = by_id.get((citation.kind, citation.id))
        if original is None or original.snippet != citation.snippet:
            return False
        if citation.domain_id != DOMAIN_ID or citation.kind not in {"capture", "confirmed_fact", "document"}:
            return False
    return True


@dataclass(frozen=True)
class _ToolSource:
    citation: SourceCitation
    body: str
    tool_name: str
    argument_name: str
    tool_id: str
    authorized_documents: dict[str, str]


def _token_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, char in enumerate(text):
        if char.isalnum():
            if start is None:
                start = index
        elif start is not None:
            spans.append((start, index))
            start = None
    if start is not None:
        spans.append((start, len(text)))
    return spans


def _plain(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _whole(value: object, *, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _budget_ok(budget: Budget) -> bool:
    if not isinstance(budget, Budget):
        return False
    if isinstance(budget.max_seconds, bool) or not isinstance(budget.max_seconds, (int, float)):
        return False
    if not math.isfinite(float(budget.max_seconds)) or budget.max_seconds <= 0:
        return False
    for name in ("max_tokens", "max_attempts", "max_calls", "max_identical"):
        if not _whole(getattr(budget, name), minimum=1):
            return False
    return True
