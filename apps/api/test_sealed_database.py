"""At-rest storage contract using new synthetic databases in pytest temp dirs."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backup_recovery import BackupError, create_backup, restore_backup
from local_captures import create_capture, list_captures
from memory_store import (
    MIGRATIONS_DIR,
    MemoryStoreError,
    SQLiteMemoryStore,
    is_synthetic_temporary_database,
)
from sealed_database import (
    MAGIC,
    KeychainUnavailable,
    PlaintextDatabaseRefused,
    SealedDatabaseError,
    seal_snapshot,
)

PASSPHRASE = "senha-sintetica-backup-2026"
CANARY = "CANARIO_DE_REPOUSO_APENAS_SINTETICO_7f14"


def _new_store(path: Path, key: bytes) -> SQLiteMemoryStore:
    store = SQLiteMemoryStore(path)
    store.unlock(key)
    return store


def _seed(store: SQLiteMemoryStore, text: str = CANARY) -> str:
    record = create_capture(store, "owner", text, datetime.now(timezone.utc))
    return record["id"]


def _crash_writer(path_value: str) -> None:
    store = _new_store(Path(path_value), secrets.token_bytes(32))
    _seed(store)
    # Deliberately bypass destructors and lifespan cleanup after a committed
    # snapshot to model abrupt process loss.
    os._exit(0)


def test_missing_key_wrong_key_and_keychain_absence_fail_closed(
    tmp_path: Path, synthetic_storage_key, wrong_storage_key,
):
    database = tmp_path / "db" / "memory.sqlite3"
    without_key = SQLiteMemoryStore(database)
    with pytest.raises(MemoryStoreError, match="chave de armazenamento necessária"):
        without_key.initialize()
    assert not database.exists()

    store = _new_store(database, synthetic_storage_key)
    _seed(store)
    store.lock()
    original = database.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()
    wrong = SQLiteMemoryStore(database)
    with pytest.raises(SealedDatabaseError):
        wrong.unlock(wrong_storage_key)
    assert not wrong.is_unlocked
    assert hashlib.sha256(database.read_bytes()).hexdigest() == original_hash
    assert CANARY.encode() not in database.read_bytes()

    with pytest.raises(KeychainUnavailable, match="chave do Keychain necessária"):
        create_backup(database, tmp_path / "backups", PASSPHRASE)
    with pytest.raises(KeychainUnavailable, match="chave do Keychain necessária"):
        restore_backup(tmp_path / "missing.jvb", tmp_path / "restores", PASSPHRASE)


def test_runtime_never_touches_default_or_non_temporary_database(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JARVIS_DATABASE_PATH", raising=False)
    default_candidate = tmp_path / "not-created" / "daily.sqlite3"
    assert not is_synthetic_temporary_database(default_candidate)
    store = SQLiteMemoryStore(default_candidate)
    with store.runtime():
        assert not default_candidate.exists()
        assert not default_candidate.parent.exists()

    configured = tmp_path / "private" / "synthetic.sqlite3"
    monkeypatch.setenv("JARVIS_DATABASE_PATH", str(configured))
    assert is_synthetic_temporary_database(configured)
    unrelated_temporary = tmp_path / "other" / "database.sqlite3"
    assert not is_synthetic_temporary_database(unrelated_temporary)


def test_new_primary_never_becomes_a_clear_sqlite_file_and_uses_memory_journal(
    tmp_path: Path, synthetic_storage_key,
):
    database = tmp_path / "private" / "memory.sqlite3"
    store = _new_store(database, synthetic_storage_key)
    try:
        _seed(store)
        assert database.read_bytes().startswith(MAGIC)
        assert not database.read_bytes().startswith(b"SQLite format 3\x00")
        assert CANARY.encode() not in database.read_bytes()
        connection = store._connect()
        try:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
            assert connection.execute("PRAGMA temp_store").fetchone()[0] == 2
            mmap_result = connection.execute("PRAGMA mmap_size").fetchone()
            assert mmap_result is None or mmap_result[0] == 0
            assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
            assert connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 0
            # SQLite refuses disk WAL for an in-memory database and keeps the
            # effective journal mode as MEMORY, even before checkpointing.
            assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "memory"
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO local_captures(id, owner, domain_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
                ("9" * 32, "owner", "dom_synthetic_a", "CANARIO_WAL_ANTES_CHECKPOINT", "2026-10-22T00:00:00+00:00"),
            )
            connection.commit()
        finally:
            connection.close()
        assert b"CANARIO_WAL_ANTES_CHECKPOINT" not in database.read_bytes()
        assert database.read_bytes().startswith(MAGIC)
        for suffix in ("-wal", "-shm", "-journal"):
            assert not Path(f"{database}{suffix}").exists()
    finally:
        store.lock()


def test_clean_lock_and_reopen_preserve_committed_data_without_residuals(
    tmp_path: Path, synthetic_storage_key,
):
    database = tmp_path / "private" / "memory.sqlite3"
    first = _new_store(database, synthetic_storage_key)
    capture_id = _seed(first)
    first.lock()
    assert not first.is_unlocked
    assert database.read_bytes().startswith(MAGIC)
    assert not any(Path(f"{database}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal"))

    second = _new_store(database, synthetic_storage_key)
    try:
        records = list_captures(second, "owner")
        assert records[0]["id"] == capture_id
        assert records[0]["text"] == CANARY
    finally:
        second.lock()


def test_crash_after_commit_leaves_ciphertext_and_missing_key_fails_closed(
    tmp_path: Path, synthetic_storage_key,
):
    database = tmp_path / "private" / "memory.sqlite3"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(Path(__file__).parent),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    child = subprocess.run(
        [sys.executable, "-c", "import sys, test_sealed_database as t; t._crash_writer(sys.argv[1])", str(database)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert child.returncode == 0, child.stderr[-1000:]
    assert database.read_bytes().startswith(MAGIC)
    assert CANARY.encode() not in database.read_bytes()

    # A crash can leave a fully authenticated ciphertext before atomic publish.
    residue = database.parent / f".{database.name}.cipher-test.pending"
    residue.write_bytes(seal_snapshot(b"SQLite format 3\x00" + bytes(64), synthetic_storage_key))
    os.chmod(residue, 0o600)
    original = database.read_bytes()
    pending = residue.read_bytes()
    locked = SQLiteMemoryStore(database)
    with pytest.raises(MemoryStoreError, match="chave de armazenamento necessária"):
        locked.initialize()
    assert database.read_bytes() == original
    assert residue.exists()  # a missing key cannot authorize recovery or cleanup
    assert residue.read_bytes() == pending
    assert original.startswith(MAGIC) and pending.startswith(MAGIC)
    assert CANARY.encode() not in original and CANARY.encode() not in pending


def test_clear_preexisting_sqlite_is_refused_and_preserved(tmp_path: Path, synthetic_storage_key):
    database = tmp_path / "private" / "memory.sqlite3"
    database.parent.mkdir(mode=0o700)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE synthetic(value TEXT)")
    connection.execute("INSERT INTO synthetic VALUES (?)", (CANARY,))
    connection.commit()
    connection.close()
    os.chmod(database, 0o600)
    original = database.read_bytes()
    digest = hashlib.sha256(original).digest()

    store = SQLiteMemoryStore(database)
    with pytest.raises(PlaintextDatabaseRefused):
        store.unlock(synthetic_storage_key)
    assert not store.is_unlocked
    assert hashlib.sha256(database.read_bytes()).digest() == digest
    assert CANARY.encode() in database.read_bytes()


def test_schema_upgrade_happens_in_memory_and_publishes_only_ciphertext(
    tmp_path: Path, synthetic_storage_key,
):
    database = tmp_path / "private" / "memory.sqlite3"
    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert len(migration_files) >= 2
    older_migrations = tmp_path / "older-migrations"
    older_migrations.mkdir(mode=0o700)
    for migration in migration_files[:-1]:
        shutil.copyfile(migration, older_migrations / migration.name)

    old = SQLiteMemoryStore(database, migrations_dir=older_migrations)
    old.unlock(synthetic_storage_key)
    # Model a database created before 0027 added capture revisions. The
    # current create_capture API writes the new version columns, so seed the
    # old schema directly instead of pretending it was a current writer.
    with old.transaction() as connection:
        connection.execute(
            "INSERT INTO local_captures(id, owner, domain_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
            ("7" * 32, "owner", "dom_synthetic_a", CANARY, "2026-10-22T00:00:00+00:00"),
        )
    old.lock()
    before = database.read_bytes()
    assert before.startswith(MAGIC) and CANARY.encode() not in before

    upgraded = _new_store(database, synthetic_storage_key)
    try:
        with upgraded.transaction() as connection:
            count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert count == len(migration_files)
        assert list_captures(upgraded, "owner")[0]["text"] == CANARY
        assert CANARY.encode() not in database.read_bytes()
    finally:
        upgraded.lock()


def test_encrypted_backup_restore_and_no_persistent_clear_copy(tmp_path: Path, synthetic_storage_key):
    source = tmp_path / "source" / "memory.sqlite3"
    store = _new_store(source, synthetic_storage_key)
    _seed(store)
    store.lock()

    archive = create_backup(source, tmp_path / "backups", PASSPHRASE, storage_key=synthetic_storage_key)
    assert archive.read_bytes().startswith(b"JARVISBK")
    assert CANARY.encode() not in archive.read_bytes()
    restored = restore_backup(
        archive,
        tmp_path / "restores",
        PASSPHRASE,
        storage_key=synthetic_storage_key,
        # The snapshot has no deletion record; restoration must be an explicit
        # choice even though it was created moments ago.
        confirm_legacy_resurrection=True,
    )
    assert restored.read_bytes().startswith(MAGIC)
    assert CANARY.encode() not in restored.read_bytes()
    reopened = _new_store(restored, synthetic_storage_key)
    try:
        assert list_captures(reopened, "owner")[0]["text"] == CANARY
    finally:
        reopened.lock()

    for candidate in tmp_path.rglob("*"):
        if candidate.is_file():
            assert CANARY.encode() not in candidate.read_bytes(), candidate

