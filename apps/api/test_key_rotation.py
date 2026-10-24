"""Rotation recovery for a synthetic sealed database. The ring is in-process.

It is not the login Keychain. File-Keychain confinement is covered by the
Rust disposable-keychain harness.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backup_recovery import create_backup, restore_backup
from database_leases import LeaseError, lock
from key_rotation import (
    ACTIVE_ACCOUNT,
    RotationInterrupted,
    journal_path,
    recover_storage_key,
    rotate_storage_key,
)
from local_captures import create_capture, delete_capture
from memory_store import SQLiteMemoryStore
from sealed_database import (
    KEY_BYTES,
    KeyMissing,
    PlaintextDatabaseRefused,
    SealedDatabaseError,
    read_encrypted_snapshot,
)

PASSPHRASE = "senha-sintetica-backup-2026"
CANARY = "fato-sintetico-rotacao"
FAULTS = (
    "after_pending_item",
    "after_staging",
    "after_rollback",
    "after_journal_prepared",
    "after_journal_published",
    "after_file_publish",
    "after_previous_item",
    "after_journal_promoted",
    "after_key_switch",
    "after_journal_committed",
    "after_cleanup",
)


class MemoryKeyRing:
    def __init__(self) -> None:
        self.slots: dict[str, bytes] = {}
        self.fail_insert = False

    def load(self, account: str) -> bytes | None:
        value = self.slots.get(account)
        return None if value is None else bytes(value)

    def insert(self, account: str, key: bytes) -> None:
        if self.fail_insert:
            raise SealedDatabaseError("chave do Keychain indisponível")
        if account in self.slots:
            raise SealedDatabaseError("item de rotação duplicado")
        self.slots[account] = bytes(key)

    def replace(self, account: str, key: bytes) -> None:
        if account not in self.slots:
            raise KeyMissing("chave antiga ausente")
        self.slots[account] = bytes(key)

    def delete(self, account: str) -> None:
        self.slots.pop(account, None)


def _bind(monkeypatch, database: Path) -> None:
    monkeypatch.setenv("JARVIS_DATABASE_PATH", str(database))


def _seed(tmp_path: Path, monkeypatch) -> tuple[Path, MemoryKeyRing, bytes, str]:
    database = tmp_path / "private" / "memory.sqlite3"
    _bind(monkeypatch, database)
    old = os.urandom(KEY_BYTES)
    store = SQLiteMemoryStore(database)
    store.unlock(old)
    kept = create_capture(store, "owner", CANARY, datetime.now(timezone.utc))
    removed = create_capture(store, "owner", "item-apagado-sintetico", datetime.now(timezone.utc))
    delete_capture(store, "owner", removed["id"], expected_revision=1)
    store.lock()
    ring = MemoryKeyRing()
    ring.insert(ACTIVE_ACCOUNT, old)
    return database, ring, old, kept["id"]


def _tombstones(database: Path, key: bytes) -> list:
    image = read_encrypted_snapshot(database, key)
    connection = sqlite3.connect(":memory:")
    try:
        from sealed_database import configure_memory_connection, load_connection
        load_connection(connection, image)
        configure_memory_connection(connection)
        return connection.execute(
            "SELECT category, domain_id, record_id FROM memory_deletion_tombstones"
        ).fetchall()
    finally:
        connection.close()


def test_rotation_commits_and_rejects_the_old_key(tmp_path, monkeypatch):
    database, ring, old, capture_id = _seed(tmp_path, monkeypatch)
    backup = create_backup(database, tmp_path / "backups", PASSPHRASE, storage_key=old)
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    assert rotate_storage_key(database, ring) == "new"
    assert recover_storage_key(database, ring) == "current"
    new = ring.load(ACTIVE_ACCOUNT)
    assert new is not None and new != old
    assert read_encrypted_snapshot(database, new)
    with pytest.raises(SealedDatabaseError):
        read_encrypted_snapshot(database, old)
    assert not database.read_bytes().startswith(b"SQLite format 3\x00")
    image = read_encrypted_snapshot(database, new)
    connection = sqlite3.connect(":memory:")
    try:
        from sealed_database import configure_memory_connection, load_connection
        load_connection(connection, image)
        configure_memory_connection(connection)
        assert connection.execute(
            "SELECT body FROM local_captures WHERE id=?", (capture_id,)
        ).fetchone()[0] == CANARY
    finally:
        connection.close()
    assert _tombstones(database, new)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash
    restored = restore_backup(
        backup, tmp_path / "restores", PASSPHRASE, storage_key=new,
        confirm_legacy_resurrection=True,
    )
    assert read_encrypted_snapshot(restored, new)
    for suffix in ("-wal", "-shm", "-journal"):
        assert not Path(f"{database}{suffix}").exists()


@pytest.mark.parametrize("point", FAULTS)
def test_crash_recovery_is_idempotent_and_keeps_content(tmp_path, monkeypatch, point):
    database, ring, old, capture_id = _seed(tmp_path, monkeypatch)
    with pytest.raises(RotationInterrupted) as caught:
        rotate_storage_key(database, ring, fault=point)
    assert caught.value.point == point
    first = recover_storage_key(database, ring)
    second = recover_storage_key(database, ring)
    assert second == "current"
    current = ring.load(ACTIVE_ACCOUNT)
    assert current is not None
    if point == "after_cleanup" or first == "new":
        assert current != old
    else:
        assert current == old
    image = read_encrypted_snapshot(database, current)
    connection = sqlite3.connect(":memory:")
    try:
        from sealed_database import configure_memory_connection, load_connection
        load_connection(connection, image)
        configure_memory_connection(connection)
        assert connection.execute(
            "SELECT body FROM local_captures WHERE id=?", (capture_id,)
        ).fetchone()[0] == CANARY
        assert connection.execute("SELECT COUNT(*) FROM memory_deletion_tombstones").fetchone()[0] == 1
    finally:
        connection.close()
    assert not database.read_bytes().startswith(b"SQLite format 3\x00")
    assert not journal_path(database).exists()


def test_missing_and_wrong_old_key_fail_before_a_pending_item(tmp_path, monkeypatch):
    database, ring, old, _capture = _seed(tmp_path, monkeypatch)
    empty = MemoryKeyRing()
    with pytest.raises(KeyMissing):
        rotate_storage_key(database, empty)
    assert empty.slots == {}
    ring.replace(ACTIVE_ACCOUNT, os.urandom(KEY_BYTES))
    with pytest.raises(SealedDatabaseError):
        rotate_storage_key(database, ring)
    assert list(ring.slots) == [ACTIVE_ACCOUNT]
    assert not journal_path(database).exists()
    ring.replace(ACTIVE_ACCOUNT, old)
    assert read_encrypted_snapshot(database, old)


def test_keychain_insert_failure_leaves_the_old_pair(tmp_path, monkeypatch):
    database, ring, old, _capture = _seed(tmp_path, monkeypatch)
    ring.fail_insert = True
    with pytest.raises(SealedDatabaseError):
        rotate_storage_key(database, ring)
    assert ring.load(ACTIVE_ACCOUNT) == old
    assert read_encrypted_snapshot(database, old)
    assert not journal_path(database).exists()


def test_corrupt_journal_fails_closed(tmp_path, monkeypatch):
    database, ring, old, _capture = _seed(tmp_path, monkeypatch)
    with pytest.raises(RotationInterrupted):
        rotate_storage_key(database, ring, fault="after_journal_prepared")
    path = journal_path(database)
    blob = bytearray(path.read_bytes())
    blob[-2] ^= 0x01
    path.write_bytes(blob)
    before = database.read_bytes()
    with pytest.raises(SealedDatabaseError):
        recover_storage_key(database, ring)
    assert database.read_bytes() == before
    assert not before.startswith(b"SQLite format 3\x00")


def test_sidecar_and_plaintext_are_refused(tmp_path, monkeypatch):
    database, ring, old, _capture = _seed(tmp_path, monkeypatch)
    wal = Path(f"{database}-wal")
    wal.write_bytes(b"not-a-clear-database")
    with pytest.raises(SealedDatabaseError):
        rotate_storage_key(database, ring)
    wal.unlink()
    clear = tmp_path / "private" / "clear.sqlite3"
    _bind(monkeypatch, clear)
    clear.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
    os.chmod(clear, 0o600)
    clear_ring = MemoryKeyRing()
    clear_ring.insert(ACTIVE_ACCOUNT, old)
    with pytest.raises(PlaintextDatabaseRefused):
        rotate_storage_key(clear, clear_ring)


def test_concurrent_lease_blocks_rotation(tmp_path, monkeypatch):
    database, ring, old, _capture = _seed(tmp_path, monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with lock(database, exclusive=True):
            started.set()
            assert release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert started.wait(2)
    try:
        with pytest.raises(LeaseError):
            rotate_storage_key(database, ring)
    finally:
        release.set()
        thread.join(2)
    assert ring.load(ACTIVE_ACCOUNT) == old
    assert not journal_path(database).exists()
