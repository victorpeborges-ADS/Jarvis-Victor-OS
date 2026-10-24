"""Contrato DEC-14: persistir identidade opaca, nunca turnos ou autorização."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artifact_store import put_artifact, read_fragment
from conversation_continuity import (
    CONVERSATION_TTL,
    conversation_exists,
    open_conversation,
)
from conversation_gateway import (
    APP_RESPONSE_MAX_BYTES,
    Budget,
    ConversationGateway,
    FakeProvider,
    ProviderCall,
    ProviderOutput,
)
from local_security import put_session_for_tests, reset_state
from memory_store import SQLiteMemoryStore
from sealed_database import MAGIC

NOW = datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
OLD_SESSION = "sessao-sintetica-antes-do-lock"
OLD_CSRF = "csrf-sintetico-nao-persistir"
PROMPT_CANARY = "prompt-canario-da-conversa"
RESPONSE_CANARY = "resposta-canario-da-conversa"
SOURCE_CANARY = "fonte-canario-da-conversa"
GRANT_CANARY = "grant-canario-da-conversa"


@pytest.fixture(autouse=True)
def _reset_sessions():
    reset_state()
    yield
    reset_state()


def _store(path: Path, encrypted_store_factory) -> SQLiteMemoryStore:
    store = encrypted_store_factory(path)
    store.initialize()
    assert path.read_bytes().startswith(MAGIC)
    return store


def _budget() -> Budget:
    return Budget(
        max_seconds=5,
        max_tokens=32,
        max_attempts=1,
        max_calls=1,
        max_identical=1,
    )


def _fields(conversation_id: str, text: str = PROMPT_CANARY) -> dict[str, object]:
    return {"conversation_id": conversation_id, "text": text, "context_tokens": 1}


def test_only_opaque_identity_survives_reopen_and_does_not_restore_authorization(tmp_path, encrypted_store_factory):
    path = tmp_path / "private" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    opened = open_conversation(store, "owner", "dom_synthetic_a", "new", NOW)
    conversation_id = opened["conversation_id"]
    assert len(conversation_id) == 32
    assert set(conversation_id) <= set("0123456789abcdef")
    assert opened["expires_at"] == (NOW + CONVERSATION_TTL).isoformat()

    seen: list[ProviderCall] = []

    def respond(call, cancel, deadline, clock):
        seen.append(call)
        return ProviderOutput(
            text=RESPONSE_CANARY,
            output_tokens=1,
            cost="unmeasured",
            repeat=False,
        )

    put_session_for_tests(OLD_SESSION, "owner", OLD_CSRF)
    provider = FakeProvider(respond)
    gateway = ConversationGateway(provider)
    result = gateway.run(OLD_SESSION, _fields(conversation_id), _budget())
    assert result.status == "completed"
    assert gateway.visible_text(OLD_SESSION, conversation_id) == RESPONSE_CANARY
    assert len(seen) == 1
    assert OLD_SESSION not in repr(seen[0])
    assert SOURCE_CANARY not in repr(seen[0])
    assert GRANT_CANARY not in repr(seen[0])

    with store.transaction() as connection:
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(local_conversations)")
        ]
        assert columns == [
            "conversation_id",
            "owner",
            "domain_id",
            "created_at",
            "last_seen_at",
            "expires_at",
        ]
        rows = connection.execute(
            "SELECT conversation_id, owner, domain_id, created_at, last_seen_at, expires_at "
            "FROM local_conversations"
        ).fetchall()
        assert [tuple(row) for row in rows] == [(
            conversation_id,
            "owner",
            "dom_synthetic_a",
            NOW.isoformat(),
            NOW.isoformat(),
            (NOW + CONVERSATION_TTL).isoformat(),
        )]
        tables = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        assert "conversation_turns" not in tables
        populated = {}
        for table in tables:
            if table == "schema_migrations":
                continue
            count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if count:
                populated[table] = count
        assert populated == {"local_conversations": 1}

    gateway.clear_all()
    assert gateway.visible_text(OLD_SESSION, conversation_id) == ""
    store.lock()
    assert path.read_bytes().startswith(MAGIC)
    assert all(
        canary.encode() not in path.read_bytes()
        for canary in (
            PROMPT_CANARY,
            RESPONSE_CANARY,
            SOURCE_CANARY,
            GRANT_CANARY,
            OLD_SESSION,
            OLD_CSRF,
        )
    )

    # Model a new process: the encrypted opaque ID remains, session/grants do not.
    reset_state()
    reopened = _store(path, encrypted_store_factory)
    resumed = open_conversation(reopened, "owner", "dom_synthetic_a", "resume", LATER)
    assert resumed["conversation_id"] == conversation_id
    assert conversation_exists(reopened, "owner", "dom_synthetic_a", conversation_id, LATER)

    later_provider = FakeProvider(respond)
    later_gateway = ConversationGateway(later_provider)
    denied = later_gateway.run(OLD_SESSION, _fields(conversation_id), _budget())
    assert denied.status == "session_required"
    assert denied.text == ""
    assert later_provider.invocations == 0
    reopened.lock()


def test_expired_conversation_id_cannot_be_resumed(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    first = open_conversation(store, "owner", "dom_synthetic_a", "new", NOW)
    refreshed = open_conversation(store, "owner", "dom_synthetic_a", "resume", LATER)
    assert refreshed["conversation_id"] == first["conversation_id"]
    expires_at = LATER + CONVERSATION_TTL
    assert refreshed["expires_at"] == expires_at.isoformat()
    assert not conversation_exists(
        store, "owner", "dom_synthetic_a", first["conversation_id"], expires_at,
    )

    after_expiry = open_conversation(
        store, "owner", "dom_synthetic_a", "resume", expires_at,
    )
    assert after_expiry["conversation_id"] != first["conversation_id"]
    assert conversation_exists(
        store, "owner", "dom_synthetic_a", after_expiry["conversation_id"], expires_at,
    )
    store.lock()


def test_large_artifact_is_read_in_a_fragment_under_the_body_ceiling(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    body = b"x" * 3000
    stored = put_artifact(store, "owner", "dom_synthetic_a", body, NOW, NOW + timedelta(days=1))
    assert stored["size"] == 3000
    assert "body" not in stored
    assert len(stored["id"]) == 32
    fragment = read_fragment(store, "owner", "dom_synthetic_a", stored["id"], 0, 512, NOW)
    assert fragment["status"] == "fragment"
    assert fragment["sha256"] == stored["sha256"]
    assert bytes.fromhex(fragment["data_hex"]) == body[:512]
    assert len(fragment["data_hex"]) < APP_RESPONSE_MAX_BYTES
    hidden = read_fragment(store, "owner", "dom_synthetic_b", stored["id"], 0, 512, NOW)
    assert hidden["status"] == "domain_rejected"
    assert hidden["data_hex"] == ""
    expired = read_fragment(
        store, "owner", "dom_synthetic_a", stored["id"], 0, 512, NOW + timedelta(days=1),
    )
    assert expired["status"] == "expired"
    assert expired["data_hex"] == ""
    store.lock()


def test_artifact_api_has_no_path_argument():
    source = Path(__file__).with_name("artifact_store.py").read_text(encoding="utf-8")
    assert "path" not in put_artifact.__code__.co_varnames
    assert "urlopen" not in source
    assert "subprocess" not in source
