"""Recoverable rotation of the sealed-database storage key.

The journal is an AES-GCM record sealed with a key that remains in the
Keychain. It stores generations and item names, never key bytes. The previous
key and previous ciphertext stay until the new pair is durably confirmed.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path

import database_leases as leases
from memory_store import is_synthetic_temporary_database
from sealed_database import (
    JOURNAL_AAD,
    KEY_BYTES,
    KeyMissing,
    PlaintextDatabaseRefused,
    SealedDatabaseError,
    configure_memory_connection,
    load_connection,
    open_record,
    open_snapshot,
    read_encrypted_snapshot,
    seal_record,
    validate_image,
    validate_key,
    write_encrypted_snapshot,
)

ACTIVE_ACCOUNT = "primary"
PHASES = ("prepared", "published", "promoted", "committed")


class RotationInterrupted(SealedDatabaseError):
    """Injected crash after a durable boundary. Not used in production."""

    def __init__(self, point: str) -> None:
        super().__init__("rotação interrompida")
        self.point = point


class KeyRing:
    """Two-slot key directory. Implementations must not log or persist keys."""

    def load(self, account: str) -> bytes | None:
        raise NotImplementedError

    def insert(self, account: str, key: bytes) -> None:
        raise NotImplementedError

    def replace(self, account: str, key: bytes) -> None:
        raise NotImplementedError

    def delete(self, account: str) -> None:
        raise NotImplementedError


def journal_path(database: Path) -> Path:
    return database.parent / f".{database.name}.rotation-journal"


def rollback_path(database: Path) -> Path:
    return database.parent / f".{database.name}.rotation-rollback"


def staging_path(database: Path, generation: str) -> Path:
    return database.parent / f".{database.name}.rotation-staging-{generation}"


def rotate_storage_key(
    database: Path,
    ring: KeyRing,
    *,
    fault: str | None = None,
) -> str:
    """Rotate one synthetic database. Returns ``new`` after a durable commit."""
    database = _database(database)
    with leases.lock(database, exclusive=True), leases.lock(database, writer=True):
        if journal_path(database).exists():
            _recover_locked(database, ring)
        return _rotate_locked(database, ring, fault)


def recover_storage_key(database: Path, ring: KeyRing) -> str:
    """Finish at the old pair or the new pair. A second call stays there."""
    database = _database(database)
    with leases.lock(database, exclusive=True), leases.lock(database, writer=True):
        return _recover_locked(database, ring)


def _rotate_locked(database: Path, ring: KeyRing, fault: str | None) -> str:
    _refuse_sidecars(database)
    old = ring.load(ACTIVE_ACCOUNT)
    if old is None:
        raise KeyMissing("chave antiga ausente")
    validate_key(old)
    try:
        image = read_encrypted_snapshot(database, old)
    except (SealedDatabaseError, PlaintextDatabaseRefused):
        raise
    fingerprint = _fingerprint(image)
    new = bytearray(secrets.token_bytes(KEY_BYTES))
    try:
        generation = hashlib.sha256(database.read_bytes()).hexdigest()[:16]
        pending = f"pending-{generation}"
        previous = f"previous-{generation}"
        ring.insert(pending, bytes(new))
        _fault(fault, "after_pending_item")
        new_file = staging_path(database, generation)
        write_encrypted_snapshot(new_file, image, new, replace=False)
        staged = read_encrypted_snapshot(new_file, new)
        if _fingerprint(staged) != fingerprint:
            raise SealedDatabaseError("rotação recusada")
        _fault(fault, "after_staging")
        _copy_ciphertext(database, rollback_path(database))
        _fault(fault, "after_rollback")
        record = {
            "protocol": 1,
            "phase": "prepared",
            "generation": generation,
            "pending_account": pending,
            "previous_account": previous,
            "old_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "new_sha256": hashlib.sha256(new_file.read_bytes()).hexdigest(),
        }
        _write_journal(database, record, old)
        _fault(fault, "after_journal_prepared")
        record["phase"] = "published"
        _write_journal(database, record, old)
        _fault(fault, "after_journal_published")
        os.replace(new_file, database)
        _sync_parent(database)
        _fault(fault, "after_file_publish")
        ring.insert(previous, old)
        _fault(fault, "after_previous_item")
        record["phase"] = "promoted"
        _write_journal(database, record, old)
        _fault(fault, "after_journal_promoted")
        ring.replace(ACTIVE_ACCOUNT, bytes(new))
        _fault(fault, "after_key_switch")
        current = ring.load(ACTIVE_ACCOUNT)
        if current != bytes(new) or _fingerprint(read_encrypted_snapshot(database, current)) != fingerprint:
            raise SealedDatabaseError("rotação recusada")
        record["phase"] = "committed"
        _write_journal(database, record, bytes(new))
        _fault(fault, "after_journal_committed")
        _cleanup(database, ring, record)
        _fault(fault, "after_cleanup")
        return "new"
    finally:
        new[:] = b"\x00" * len(new)


def _recover_locked(database: Path, ring: KeyRing) -> str:
    path = journal_path(database)
    if not path.exists():
        _remove_staging(database)
        _remove_file(rollback_path(database))
        active = ring.load(ACTIVE_ACCOUNT)
        if active is not None and database.exists():
            read_encrypted_snapshot(database, active)
            generation = hashlib.sha256(database.read_bytes()).hexdigest()[:16]
            ring.delete(f"pending-{generation}")
            ring.delete(f"previous-{generation}")
        return "current"
    active = ring.load(ACTIVE_ACCOUNT)
    record, sealing_key = _open_journal(database, ring, active)
    phase = record.get("phase")
    if phase not in PHASES or record.get("protocol") != 1:
        raise SealedDatabaseError("journal de rotação inválido")
    pending = str(record["pending_account"])
    previous = str(record["previous_account"])
    old_sha = str(record["old_sha256"])
    new_sha = str(record["new_sha256"])
    primary_sha = hashlib.sha256(database.read_bytes()).hexdigest() if database.exists() else ""
    rollback = rollback_path(database)
    if phase == "prepared":
        _remove_file(staging_path(database, str(record["generation"])))
        _remove_file(rollback)
        ring.delete(pending)
        ring.delete(previous)
        _remove_file(path)
        return "old"
    if phase == "published":
        if primary_sha == new_sha and ring.load(pending) is not None:
            record["phase"] = "promoted"
            old_key = ring.load(previous) or sealing_key
            _write_journal(database, record, old_key)
            phase = "promoted"
        else:
            if rollback.exists():
                os.replace(rollback, database)
                _sync_parent(database)
            _remove_file(staging_path(database, str(record["generation"])))
            ring.delete(pending)
            ring.delete(previous)
            _remove_file(path)
            return "old"
    if phase == "promoted":
        new_key = ring.load(pending)
        if new_key is None or primary_sha != new_sha:
            old_key = ring.load(previous) or sealing_key
            if rollback.exists() and old_key is not None:
                os.replace(rollback, database)
                _sync_parent(database)
                ring.replace(ACTIVE_ACCOUNT, old_key)
            ring.delete(pending)
            ring.delete(previous)
            _remove_file(path)
            return "old"
        ring.replace(ACTIVE_ACCOUNT, new_key)
        record["phase"] = "committed"
        _write_journal(database, record, new_key)
        phase = "committed"
    if phase == "committed":
        current = ring.load(ACTIVE_ACCOUNT)
        if current is None or hashlib.sha256(database.read_bytes()).hexdigest() != new_sha:
            raise SealedDatabaseError("journal de rotação inválido")
        read_encrypted_snapshot(database, current)
        _cleanup(database, ring, record)
        return "new"
    raise SealedDatabaseError("journal de rotação inválido")


def _cleanup(database: Path, ring: KeyRing, record: dict) -> None:
    ring.delete(str(record["pending_account"]))
    ring.delete(str(record["previous_account"]))
    _remove_file(rollback_path(database))
    _remove_file(staging_path(database, str(record["generation"])))
    _remove_file(journal_path(database))
    _sync_parent(database)


def _open_journal(database: Path, ring: KeyRing, active: bytes | None) -> tuple[dict, bytes]:
    blob = _read_private(journal_path(database))
    if blob.startswith(b"SQLite format 3\x00"):
        raise PlaintextDatabaseRefused("banco SQLite preexistente sem cifra recusado")
    keys: list[bytes] = []
    if active is not None:
        keys.append(active)
    generation = ""
    if database.exists():
        generation = hashlib.sha256(database.read_bytes()).hexdigest()[:16]
    rollback = rollback_path(database)
    if rollback.exists():
        generation = hashlib.sha256(rollback.read_bytes()).hexdigest()[:16]
    for account in (f"pending-{generation}", f"previous-{generation}"):
        loaded = ring.load(account)
        if loaded is not None and loaded not in keys:
            keys.append(loaded)
    for key in keys:
        try:
            payload = open_record(blob, key, JOURNAL_AAD)
            return json.loads(payload.decode("utf-8")), key
        except (SealedDatabaseError, UnicodeError, json.JSONDecodeError):
            continue
    raise SealedDatabaseError("journal de rotação inválido")


def _write_journal(database: Path, record: dict, key: bytes) -> None:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    blob = seal_record(payload, key, JOURNAL_AAD)
    path = journal_path(database)
    temporary = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        view = memoryview(blob)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("gravação incompleta")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    _sync_parent(database)


def _fingerprint(image: bytes) -> tuple:
    validate_image(image)
    connection = sqlite3.connect(":memory:")
    try:
        load_connection(connection, image)
        configure_memory_connection(connection)
        migrations = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        captures = connection.execute(
            "SELECT id, body FROM local_captures ORDER BY id"
        ).fetchall()
        tombstones = connection.execute(
            """SELECT category, domain_id, record_id, deleted_revision, content_sha256
               FROM memory_deletion_tombstones ORDER BY category, domain_id, record_id"""
        ).fetchall()
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).lower() != "memory":
            raise SealedDatabaseError("SQLite não permaneceu exclusivamente em memória")
    finally:
        connection.close()
    return (tuple(migrations), tuple(captures), tuple(tombstones))


def _copy_ciphertext(source: Path, destination: Path) -> None:
    blob = _read_private(source)
    if blob.startswith(b"SQLite format 3\x00"):
        raise PlaintextDatabaseRefused("banco SQLite preexistente sem cifra recusado")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        view = memoryview(blob)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("gravação incompleta")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_parent(source)


def _read_private(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SealedDatabaseError("arquivo de banco inseguro")
        return os.read(fd, info.st_size)
    finally:
        os.close(fd)


def _remove_file(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        path.unlink()


def _remove_staging(database: Path) -> None:
    for candidate in database.parent.glob(f".{database.name}.rotation-staging-*"):
        _remove_file(candidate)


def _refuse_sidecars(database: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        residual = Path(f"{database}{suffix}")
        if residual.exists() or residual.is_symlink():
            raise SealedDatabaseError("arquivo SQLite auxiliar residual; manutenção necessária")


def _sync_parent(database: Path) -> None:
    leases.sync_directory(database.parent)


def _database(database: Path) -> Path:
    database = leases.checked_path(database)
    if not is_synthetic_temporary_database(database):
        raise SealedDatabaseError("rotação recusada")
    if database.is_symlink():
        raise SealedDatabaseError("arquivo de banco inseguro")
    return database


def _fault(requested: str | None, point: str) -> None:
    if requested == point:
        raise RotationInterrupted(point)
