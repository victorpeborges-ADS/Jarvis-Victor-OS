"""Daily capture gate: local SQLite only, no network and no model."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile

import pytest

from backup_recovery import create_backup, restore_backup
from local_captures import create_capture, delete_capture, list_captures, update_capture
from memory_store import MIGRATIONS_DIR, SQLiteMemoryStore

BACKUP_PASSPHRASE = "sintetica-backup-local"


def _store(path: Path) -> SQLiteMemoryStore:
    store = SQLiteMemoryStore(path)
    store.initialize()
    return store


def test_capture_crud_survives_a_new_store(tmp_path):
    path = tmp_path / "private" / "memory.sqlite3"
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store = _store(path)
    created = create_capture(store, "owner", "ideia estavel", now)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    reopened = SQLiteMemoryStore(path)
    reopened.initialize()
    listed = list_captures(reopened, "owner")
    assert listed == [{"id": created["id"], "text": "ideia estavel", "created_at": created["created_at"]}]
    edited = update_capture(reopened, "owner", created["id"], "ideia editada")
    assert edited["id"] == created["id"]
    assert edited["created_at"] == created["created_at"]
    edited_store = SQLiteMemoryStore(path)
    edited_store.initialize()
    assert list_captures(edited_store, "owner")[0]["text"] == "ideia editada"
    delete_capture(edited_store, "owner", created["id"])
    assert list_captures(edited_store, "owner") == []


def test_capture_survives_a_new_process(tmp_path):
    path = tmp_path / "private" / "memory.sqlite3"
    program = """
import sys
from datetime import datetime, timezone
from memory_store import SQLiteMemoryStore
from local_captures import create_capture, list_captures
path, text, mode = sys.argv[1:]
store = SQLiteMemoryStore(path)
store.initialize()
if mode == "write":
    create_capture(store, "owner", text, datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc))
else:
    items = list_captures(store, "owner")
    if not items or items[0]["text"] != text:
        raise SystemExit(3)
"""
    env = os.environ.copy()
    env.pop("JARVIS_DATABASE_PATH", None)
    for mode in ("write", "read"):
        completed = subprocess.run(
            [sys.executable, "-c", program, str(path), "ideia de processo", mode],
            cwd=Path(__file__).parent,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr


def test_migration_adds_empty_capture_table(tmp_path):
    old_dir = tmp_path / "migrations-before-captures"
    old_dir.mkdir()
    for migration in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if migration.name == "0016_local_captures.sql":
            continue
        copyfile(migration, old_dir / migration.name)
    path = tmp_path / "private" / "memory.sqlite3"
    SQLiteMemoryStore(path, migrations_dir=old_dir).initialize()
    with __import__("sqlite3").connect(path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "local_captures" not in names
    store = SQLiteMemoryStore(path)
    store.initialize()
    created = create_capture(store, "owner", "depois da migracao", datetime.now(timezone.utc))
    assert list_captures(store, "owner")[0]["id"] == created["id"]


def test_private_directory_and_unusable_parent_fail_closed(tmp_path):
    path = tmp_path / "private" / "memory.sqlite3"
    store = _store(path)
    os.chmod(path.parent, 0o755)
    with pytest.raises(PermissionError):
        SQLiteMemoryStore(path).initialize()
    os.chmod(path.parent, 0o700)
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        SQLiteMemoryStore(blocker / "memory.sqlite3").initialize()


def test_backup_restores_capture_without_replacing_source(tmp_path):
    path = tmp_path / "daily" / "memory.sqlite3"
    store = _store(path)
    created = create_capture(store, "owner", "ideia para backup", datetime.now(timezone.utc))
    before = path.read_bytes()
    archive = create_backup(path, tmp_path / "backups", BACKUP_PASSPHRASE)
    restored = restore_backup(archive, tmp_path / "restores", BACKUP_PASSPHRASE)
    assert path.read_bytes() == before
    assert restored.resolve() != path.resolve()
    restored_store = SQLiteMemoryStore(restored)
    restored_store.initialize()
    assert list_captures(restored_store, "owner")[0]["text"] == "ideia para backup"
    source_again = SQLiteMemoryStore(path)
    source_again.initialize()
    assert list_captures(source_again, "owner")[0]["id"] == created["id"]


def test_capture_module_has_no_network_client():
    source = Path(__file__).with_name("local_captures.py").read_text(encoding="utf-8")
    for banned in ("httpx", "urllib", "socket", "requests", "openai"):
        assert banned not in source
