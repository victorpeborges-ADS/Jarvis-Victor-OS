"""Daily capture gate: local SQLite only, no network and no model."""

from __future__ import annotations

import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile

import pytest

from backup_recovery import (
    LegacyDeletionConfirmationRequired,
    create_backup,
    restore_backup,
)
from local_captures import (
    create_capture,
    delete_capture,
    list_captures,
    open_capture,
    search_captures,
    update_capture,
)
from memory_store import MIGRATIONS_DIR, SQLiteMemoryStore

BACKUP_PASSPHRASE = "sintetica-backup-local"


def _store(path: Path, encrypted_store_factory) -> SQLiteMemoryStore:
    store = encrypted_store_factory(path)
    store.initialize()
    return store


def test_capture_crud_survives_a_new_store(tmp_path, encrypted_store_factory):
    path = tmp_path / "private" / "memory.sqlite3"
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store = _store(path, encrypted_store_factory)
    created = create_capture(store, "owner", "ideia estavel", now)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    reopened = _store(path, encrypted_store_factory)
    listed = list_captures(reopened, "owner")
    assert listed == [{"id": created["id"], "text": "ideia estavel", "created_at": created["created_at"]}]
    edited = update_capture(reopened, "owner", created["id"], "ideia editada")
    assert edited["id"] == created["id"]
    assert edited["created_at"] == created["created_at"]
    edited_store = _store(path, encrypted_store_factory)
    assert list_captures(edited_store, "owner")[0]["text"] == "ideia editada"
    delete_capture(edited_store, "owner", created["id"])
    assert list_captures(edited_store, "owner") == []


def test_capture_search_opens_origin_and_forgets_the_old_text(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    now = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
    created = create_capture(store, "owner", "reunião sintética", now)
    create_capture(store, "owner", "outra nota local", now.replace(minute=5))
    found, omitted = search_captures(store, "owner", "reuniao")
    assert omitted == 0
    assert [item["id"] for item in found] == [created["id"]]
    assert search_captures(store, "owner", "a%b") == ([], 0)
    opened = open_capture(store, "owner", created["id"])
    assert opened == {
        "id": created["id"],
        "text": "reunião sintética",
        "created_at": created["created_at"],
        "domain_id": "dom_synthetic_a",
        "category": "explicit_capture",
    }
    update_capture(store, "owner", created["id"], "pauta corrigida")
    assert search_captures(store, "owner", "reuniao") == ([], 0)
    corrected, omitted_after_edit = search_captures(store, "owner", "pauta")
    assert omitted_after_edit == 0 and corrected[0]["text"] == "pauta corrigida"
    delete_capture(store, "owner", created["id"])
    # Apagar vale para este banco aberto. Um backup anterior pode repor o texto; isso não é testado aqui.
    assert search_captures(store, "owner", "pauta") == ([], 0)
    with pytest.raises(ValueError):
        open_capture(store, "owner", created["id"])
    with store.transaction() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM local_captures WHERE id = ?", (created["id"],)
        ).fetchone()[0] == 0


def test_capture_search_is_literal_and_reports_matches_left_out(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    base = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)
    texts = [
        "é" * 80,
        "marca % literal",
        "marca _ literal",
        'marca "aspas"',
        "marca antiga",
    ]
    created = [
        create_capture(store, "owner", text, base.replace(minute=index))
        for index, text in enumerate(texts)
    ]
    shown, omitted = search_captures(store, "owner", "marca")
    assert omitted == 1
    assert [item["id"] for item in shown] == [created[4]["id"], created[3]["id"], created[2]["id"]]
    assert created[1]["id"] not in {item["id"] for item in shown}
    assert search_captures(store, "owner", "%")[0][0]["text"] == "marca % literal"
    assert search_captures(store, "owner", "_")[0][0]["text"] == "marca _ literal"
    assert search_captures(store, "owner", '"')[0][0]["text"] == 'marca "aspas"'
    accent, accent_omitted = search_captures(store, "owner", "e" * 10)
    assert accent_omitted == 0 and accent[0]["text"] == "é" * 80
    for query in ("", "x" * 81):
        with pytest.raises(ValueError):
            search_captures(store, "owner", query)
    with pytest.raises(ValueError):
        create_capture(store, "owner", "y" * 81, base)
    missing = "0123456789abcdef0123456789abcdef"
    with pytest.raises(ValueError):
        open_capture(store, "owner", missing)
    with pytest.raises(ValueError):
        update_capture(store, "owner", missing, "nao existe")
    with pytest.raises(ValueError):
        delete_capture(store, "owner", missing)
    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO local_captures(id, owner, domain_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
                (missing, "owner", "dom_synthetic_b", "outro dominio", base.isoformat()),
            )


def test_capture_survives_store_reopen_with_process_local_key(tmp_path, encrypted_store_factory):
    path = tmp_path / "private" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    created = create_capture(
        store, "owner", "ideia após reabertura",
        datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
    )
    store.lock()
    reopened = _store(path, encrypted_store_factory)
    assert list_captures(reopened, "owner") == [{
        "id": created["id"],
        "text": "ideia após reabertura",
        "created_at": created["created_at"],
    }]


def test_migration_adds_empty_capture_table(tmp_path, encrypted_store_factory):
    old_dir = tmp_path / "migrations-before-captures"
    old_dir.mkdir()
    for migration in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if migration.name in {
            "0016_local_captures.sql",
            "0027_memory_capture_revisions.sql",
        }:
            continue
        copyfile(migration, old_dir / migration.name)
    path = tmp_path / "private" / "memory.sqlite3"
    old_store = encrypted_store_factory(path, migrations_dir=old_dir)
    old_store.initialize()
    with old_store.transaction() as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "local_captures" not in names
    store = _store(path, encrypted_store_factory)
    created = create_capture(store, "owner", "depois da migracao", datetime.now(timezone.utc))
    assert list_captures(store, "owner")[0]["id"] == created["id"]


def test_private_directory_and_unusable_parent_fail_closed(tmp_path, encrypted_store_factory):
    path = tmp_path / "private" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    os.chmod(path.parent, 0o755)
    with pytest.raises(PermissionError):
        encrypted_store_factory(path).initialize()
    os.chmod(path.parent, 0o700)
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        encrypted_store_factory(blocker / "memory.sqlite3").initialize()


def test_backup_restores_capture_without_replacing_source(tmp_path, encrypted_store_factory):
    path = tmp_path / "daily" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    created = create_capture(store, "owner", "ideia para backup", datetime.now(timezone.utc))
    before = path.read_bytes()
    archive = create_backup(
        path, tmp_path / "backups", BACKUP_PASSPHRASE, storage_key=encrypted_store_factory.storage_key,
    )
    restored = restore_backup(
        archive, tmp_path / "restores", BACKUP_PASSPHRASE, storage_key=encrypted_store_factory.storage_key,
        confirm_legacy_resurrection=True,
    )
    assert path.read_bytes() == before
    assert restored.resolve() != path.resolve()
    restored_store = _store(restored, encrypted_store_factory)
    assert list_captures(restored_store, "owner")[0]["text"] == "ideia para backup"
    source_again = _store(path, encrypted_store_factory)
    assert list_captures(source_again, "owner")[0]["id"] == created["id"]


def test_open_database_purge_hides_capture_but_prior_backup_keeps_it(tmp_path, encrypted_store_factory):
    path = tmp_path / "daily" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    created = create_capture(store, "owner", "texto que sai do banco aberto", datetime.now(timezone.utc))
    archive = create_backup(
        path, tmp_path / "backups", BACKUP_PASSPHRASE, storage_key=encrypted_store_factory.storage_key,
    )
    delete_capture(store, "owner", created["id"])
    assert search_captures(store, "owner", "texto") == ([], 0)
    with pytest.raises(ValueError):
        open_capture(store, "owner", created["id"])
    reopened = _store(path, encrypted_store_factory)
    assert list_captures(reopened, "owner") == []
    with reopened.transaction() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM local_captures WHERE id = ?", (created["id"],)
        ).fetchone()[0] == 0
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )}
    assert "local_captures_fts" not in tables
    with pytest.raises(LegacyDeletionConfirmationRequired):
        restore_backup(
            archive, tmp_path / "restores", BACKUP_PASSPHRASE,
            storage_key=encrypted_store_factory.storage_key,
        )
    restored = restore_backup(
        archive, tmp_path / "restores", BACKUP_PASSPHRASE,
        storage_key=encrypted_store_factory.storage_key, confirm_legacy_resurrection=True,
    )
    restored_store = _store(restored, encrypted_store_factory)
    assert list_captures(restored_store, "owner")[0]["text"] == "texto que sai do banco aberto"
    assert list_captures(reopened, "owner") == []


def test_capture_module_has_no_network_client():
    source = Path(__file__).with_name("local_captures.py").read_text(encoding="utf-8")
    for banned in ("httpx", "urllib", "socket", "requests", "openai"):
        assert banned not in source
