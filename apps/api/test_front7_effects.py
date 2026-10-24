"""Frente 7 com serviço falso. O smoke da janela não vira passe."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from approved_effect import (
    WINDOW_SMOKE,
    approval_sha,
    cancel_effect,
    dispatch_effect,
    dry_run,
    prepare_effect,
    retry_dispatch,
    revoke_effect,
    submit_notice,
)
from memory_store import SQLiteMemoryStore

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
QUIET = datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)


def _store(path: Path, encrypted_store_factory) -> SQLiteMemoryStore:
    store = encrypted_store_factory(path)
    store.initialize()
    return store


def _sha(version: str = "v1") -> str:
    return approval_sha(version, "operador@example.test", "texto exato")


def test_dry_run_does_not_write_and_new_version_invalidates_approval(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    plan = dry_run("v1", "operador@example.test", "texto exato")
    assert plan["dispatched"] == "false"
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM prepared_effects").fetchone()[0] == 0
    prepared = prepare_effect(
        store, "dom_synthetic_a", "v1", "operador@example.test", "texto exato", _sha(),
    )
    with pytest.raises(ValueError, match="efeito recusado"):
        dispatch_effect(store, "dom_synthetic_a", prepared["id"], "v2")
    assert prepared["status"] == "prepared"
    assert prepared["confirmed"] == 0


def test_retry_does_not_duplicate_and_cancel_keeps_a_confirmed_effect(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    prepared = prepare_effect(
        store, "dom_synthetic_a", "v1", "operador@example.test", "texto exato", _sha(),
    )
    sent = dispatch_effect(store, "dom_synthetic_a", prepared["id"], "v1")
    again = retry_dispatch(store, "dom_synthetic_a", prepared["id"], "v1")
    assert again["id"] == sent["id"]
    assert again["status"] == "succeeded"
    assert cancel_effect(store, "dom_synthetic_a", prepared["id"]) == "succeeded"
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM prepared_effects").fetchone()[0] == 1
        assert tuple(connection.execute(
            "SELECT status, confirmed FROM prepared_effects"
        ).fetchone()) == ("succeeded", 1)


def test_cancel_before_dispatch_and_revocation_block_the_effect(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    first = prepare_effect(
        store, "dom_synthetic_a", "v1", "operador@example.test", "texto exato", _sha(),
    )
    assert cancel_effect(store, "dom_synthetic_a", first["id"]) == "cancelled"
    with pytest.raises(ValueError, match="efeito recusado"):
        dispatch_effect(store, "dom_synthetic_a", first["id"], "v1")
    second = prepare_effect(
        store, "dom_synthetic_a", "v2", "operador@example.test", "outro texto",
        approval_sha("v2", "operador@example.test", "outro texto"),
    )
    revoke_effect(store, "dom_synthetic_a", second["id"])
    with pytest.raises(ValueError, match="efeito recusado"):
        dispatch_effect(store, "dom_synthetic_a", second["id"], "v2")


def test_partial_prepare_writes_nothing(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    with pytest.raises(ValueError, match="efeito recusado"):
        prepare_effect(store, "dom_synthetic_a", "v1", "pessoa@gmail.com", "texto exato", _sha())
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM prepared_effects").fetchone()[0] == 0


def test_attention_dedup_quiet_hours_backpressure_and_lateness(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    fingerprint = "ab" * 32
    first = submit_notice(
        store, fingerprint, NOW, quiet=False, late_seconds=0, cost="não medido", foreground=False,
    )
    second = submit_notice(
        store, fingerprint, NOW, quiet=False, late_seconds=0, cost="1.0000", foreground=False,
    )
    assert second["id"] == first["id"]
    assert second["cost"] == "não medido"
    deferred = submit_notice(
        store, "cd" * 32, QUIET, quiet=False, late_seconds=0, cost="não medido", foreground=False,
    )
    assert deferred["status"] == "deferred"
    suppressed = submit_notice(
        store, "ef" * 32, NOW, quiet=False, late_seconds=0, cost="não medido", foreground=True,
    )
    assert suppressed["status"] == "suppressed"
    submit_notice(
        store, f"{0:064x}", NOW, quiet=False, late_seconds=0, cost="não medido", foreground=False,
    )
    with pytest.raises(ValueError, match="aviso recusado"):
        submit_notice(
            store, "ff" * 32, NOW, quiet=False, late_seconds=0, cost="não medido", foreground=False,
        )
    missed = submit_notice(
        store, "11" * 32, NOW, quiet=False, late_seconds=301, cost="não medido", foreground=False,
    )
    assert missed["status"] == "missed"
    assert WINDOW_SMOKE == "BLOCKED"


def test_module_does_not_send() -> None:
    source = Path(__file__).with_name("approved_effect.py").read_text(encoding="utf-8")
    for needle in ("subprocess", "socket", "urlopen", "smtp"):
        assert needle not in source
