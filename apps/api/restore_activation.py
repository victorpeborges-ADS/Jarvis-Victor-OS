"""Offline, exact-schema activation. No default database, routes or workers.

PREPARED is the write-ahead authority for replacement. Until COMMITTED is
durable recovery reinstalls the independent rollback-ready image. Committed
databases may have legitimate later writes and are never rolled back implicitly.
All artifacts (including failed staging) are retained. Locks are advisory and
the origin restriction is not protection against malicious same-UID software.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import database_leases as leases
from sealed_database import MAGIC as SEALED_DATABASE_MAGIC, SQLITE_HEADER
from backup_recovery import (
    BackupError, MAX_DATABASE_BYTES, MIGRATIONS_DIR, _expected_migration_checksums,
    _open_archive, _read_backup_file, _snapshot_database, _validate_database_file,
    _validate_snapshot_image, _verify_source_files, _write_all, validate_activation_image, _prepare_restore_image,
)


class ActivationError(BackupError):
    pass


def _point(name: str) -> None:
    """Fault-injection seam; production never selects failures from environment."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _read(path: Path, limit: int = MAX_DATABASE_BYTES) -> bytes:
    leases.checked_path(path)
    before = leases.private_stat(path)
    if before.st_size > limit:
        raise ActivationError("arquivo excede limite de manutenção")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ActivationError("identidade do arquivo mudou")
        chunks = []
        total = 0
        while chunk := os.read(fd, min(1024 * 1024, limit + 1 - total)):
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ActivationError("arquivo excede limite de manutenção")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _durable_new(path: Path, payload: bytes, label: str) -> None:
    _point(label + ":before_write")
    leases.checked_path(path)
    leases.private_stat(path.parent, directory=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        _write_all(fd, payload)
        _point(label + ":after_write")
        os.fsync(fd)
        _point(label + ":after_fsync")
    finally:
        os.close(fd)
    leases.sync_directory(path.parent)
    _point(label + ":after_dirsync")


def _ledger(database: Path) -> Path:
    return leases.names(database)[3]


def _state(database: Path) -> dict | None:
    root = _ledger(database)
    if not root.exists() and not root.is_symlink():
        return None
    leases.private_stat(root, directory=True)
    payload = _read(root / "state.json", 4096)
    try:
        record = json.loads(payload)
        if (not isinstance(record, dict) or set(record) != {"version", "operation", "state", "old", "new", "schema"}
                or type(record["version"]) is not int or record["version"] != 1
                or not isinstance(record["operation"], str)
                or not re.fullmatch(r"[a-f0-9]{32}", record["operation"])
                or record["state"] not in {"BUILDING", "PREPARED", "SWITCHED", "COMMITTED", "ROLLED_BACK", "ABORTED"}
                or payload != _json(record)):
            raise ValueError
        for field in ("old", "new", "schema"):
            if not isinstance(record[field], str) or not re.fullmatch(r"[a-f0-9]{64}", record[field]):
                raise ValueError
        return record
    except (ValueError, TypeError, KeyError) as exc:
        raise ActivationError("registro de ativação inválido; manutenção necessária") from exc


def _record(database: Path, record: dict, state: str) -> None:
    root = _ledger(database)
    updated = dict(record, state=state)
    # Keep abandoned partial records for diagnostics; never overwrite one.
    temporary = root / ("record-" + secrets.token_hex(16) + ".json")
    _durable_new(temporary, _json(updated), "record-" + state)
    _point(state + ":before_publish")
    os.replace(temporary, root / "state.json")
    _point(state + ":after_publish")
    leases.sync_directory(root)
    _point(state + ":durable")
    record.update(updated)


def _schema() -> str:
    return _sha(_json({"activation_protocol": 1, "migrations": _expected_migration_checksums(MIGRATIONS_DIR)}))


def _require_origin(database: Path) -> None:
    if not leases.enrolled(database):
        raise ActivationError("ativação bloqueada: banco preexistente ao protocolo de leases")


def assert_ready(database: Path) -> None:
    record = _state(database)
    if record and record["state"] not in {"COMMITTED", "ROLLED_BACK", "ABORTED"}:
        raise ActivationError("ativação pendente; reinicie para recuperar offline")
    if record and (record["schema"] != _schema() or not database.exists()):
        raise ActivationError("banco ativado incompatível ou ausente; manutenção necessária")


def _files(database: Path) -> None:
    leases.checked_path(database)
    _verify_source_files(database)
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(str(database) + suffix)
        if path.exists() or path.is_symlink():
            leases.private_stat(path)


def _no_sidecars(database: Path) -> None:
    if any(Path(str(database) + suffix).exists() or Path(str(database) + suffix).is_symlink()
           for suffix in ("-wal", "-shm", "-journal")):
        raise ActivationError("arquivos auxiliares pendentes; manutenção necessária")


def _require_legacy_sqlite(database: Path) -> None:
    """Classify the target before any SQLite API can open it."""
    try:
        before = leases.private_stat(database)
    except FileNotFoundError:
        return
    if before.st_size > MAX_DATABASE_BYTES:
        raise ActivationError("arquivo excede limite de manutenção")
    fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ActivationError("identidade do arquivo mudou")
        header = os.read(fd, len(SQLITE_HEADER))
    finally:
        os.close(fd)
    if header.startswith(SEALED_DATABASE_MAGIC):
        raise ActivationError(
            "ativação legada não suporta snapshot selado; use restauração isolada"
        )
    if header != SQLITE_HEADER:
        raise ActivationError("arquivo SQLite legado inválido")


def _consolidate(database: Path, storage_key: bytes | None = None) -> None:
    """SQLite owns journal recovery and removal. Never unlink active sidecars."""
    _files(database)
    if storage_key is not None:
        _no_sidecars(database)
        _validate_file(database, storage_key)
        leases.sync_directory(database.parent)
        return
    _require_legacy_sqlite(database)
    connection = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=0, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout=0")
        connection.execute("PRAGMA synchronous=FULL")
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result[0] != 0 or (result[1], result[2]) not in {(0, 0), (-1, -1)}:
            raise ActivationError("não foi possível consolidar WAL com exclusividade")
        if connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
            raise ActivationError("banco não entrou em estado seguro")
    finally:
        connection.close()
    # DELETE mode must leave a stand-alone database. Unexpected files block.
    _no_sidecars(database)
    _files(database)
    _validate_file(database, storage_key)
    fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    leases.sync_directory(database.parent)



def _snapshot(database: Path, storage_key: bytes | None) -> bytes:
    if storage_key is None:
        _require_legacy_sqlite(database)
        return _snapshot_database(database)
    from sealed_database import read_encrypted_snapshot
    _no_sidecars(database)
    return validate_activation_image(read_encrypted_snapshot(database, storage_key))


def _validate_file(database: Path, storage_key: bytes | None) -> None:
    if storage_key is None:
        _validate_database_file(database)
    else:
        _snapshot(database, storage_key)


def _space(database: Path, candidate_size: int) -> None:
    # Candidate, preserved rollback, rollback-ready, validation/SQLite copies,
    # journal headroom and reserve. ENOSPC is still handled at every I/O call.
    current = sum(Path(str(database) + s).stat().st_size for s in ("", "-wal", "-shm", "-journal")
                  if Path(str(database) + s).exists())
    required = 4 * (current + candidate_size) + 16 * 1024 * 1024
    if shutil.disk_usage(database.parent).free < required:
        raise ActivationError("espaço insuficiente para ativação e rollback")


@dataclass(frozen=True)
class ActivationPlan:
    database: Path
    image: bytes
    archive_hash: str
    active_hash: str
    schema_hash: str
    sealed: bool = False

    @property
    def confirmation(self) -> str:
        binding = {"destination": str(self.database), "archive": self.archive_hash,
                   "image": _sha(self.image), "active": self.active_hash, "schema": self.schema_hash, "sealed": self.sealed}
        return "ATIVAR " + _sha(_json(binding))


def prepare_activation(backup: Path | str, database: Path | str, passphrase: str, *, storage_key: bytes | None = None, confirm_legacy_resurrection: bool = False) -> ActivationPlan:
    """Read/validate only; explicit target is mandatory. No implicit default."""
    target = leases.checked_path(database)
    source = leases.checked_path(backup)
    leases.private_stat(source)
    _, archive = _read_backup_file(source)
    image = _open_archive(archive, passphrase)
    _validate_snapshot_image(image)
    with leases.lock(target, exclusive=True), leases.lock(target, writer=True):
        _require_origin(target)
        assert_ready(target)
        _files(target)
        _space(target, len(image))
        current = _snapshot(target, storage_key)
        image = _prepare_restore_image(image, confirm_legacy_resurrection=confirm_legacy_resurrection, current_image=current)
        return ActivationPlan(target, image, _sha(archive), _sha(current), _schema(), storage_key is not None)


def _suspend(database: Path, storage_key: bytes | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    connection = sqlite3.connect(":memory:" if storage_key is not None else database, isolation_level=None)
    try:
        if storage_key is not None:
            from sealed_database import configure_memory_connection, write_encrypted_snapshot
            connection.deserialize(_snapshot(database, storage_key))
            configure_memory_connection(connection)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        _point("suspend:begin")
        connection.execute("UPDATE local_automations SET state='paused', next_run_at_utc=NULL, updated_at=? WHERE state='active'", (now,))
        _point("suspend:paused")
        connection.execute("UPDATE local_automation_runs SET status='superseded', next_attempt_at_utc=NULL, error_code='restore_activation', completed_at=?, updated_at=? WHERE status IN ('pending','deferred','retry_wait','running')", (now, now))
        _point("suspend:runs")
        connection.execute("COMMIT")
        if storage_key is not None:
            write_encrypted_snapshot(database, connection.serialize(), storage_key, replace=True)
        _point("suspend:committed")
    finally:
        connection.close()


def _check_leases(database: Path, maintenance_fd: int, writer_fd: int) -> None:
    for path, fd in zip(leases.names(database)[:2], (maintenance_fd, writer_fd)):
        info, opened = leases.private_stat(path), os.fstat(fd)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise ActivationError("lease obsoleta antes da ativação")


def activate(plan: ActivationPlan, confirmation: str, *, storage_key: bytes | None = None) -> Path:
    if not isinstance(plan, ActivationPlan) or confirmation != plan.confirmation:
        raise ActivationError("confirmação explícita da ativação inválida")
    if plan.sealed != (storage_key is not None):
        raise ActivationError("modo de armazenamento diverge do plano")
    database = leases.checked_path(plan.database)
    # Revalidation prevents a forged/stale plan from bypassing schema checks.
    image = validate_activation_image(plan.image)
    if _schema() != plan.schema_hash:
        raise ActivationError("runtime mudou; refaça a confirmação")
    with leases.lock(database, exclusive=True) as maintenance_fd, leases.lock(database, writer=True) as writer_fd:
        _require_origin(database)
        assert_ready(database)
        _files(database)
        current_image = _snapshot(database, storage_key)
        if _sha(current_image) != plan.active_hash:
            raise ActivationError("banco mudou; refaça a confirmação")
        # Recheck under both leases, even for a manually constructed plan.
        image = _prepare_restore_image(image, confirm_legacy_resurrection=True, current_image=current_image)
        _space(database, len(image))
        root = _ledger(database)
        if not root.exists():
            root.mkdir(mode=0o700)
            leases.sync_directory(database.parent)
        leases.private_stat(root, directory=True)
        if root.stat().st_dev != database.parent.stat().st_dev:
            raise ActivationError("staging deve estar no volume do destino")
        operation = secrets.token_hex(16)
        record = {"version": 1, "operation": operation, "state": "BUILDING",
                  "old": plan.active_hash, "new": _sha(image), "schema": plan.schema_hash}
        _record(database, record, "BUILDING")
        area = root / operation
        area.mkdir(mode=0o700)
        leases.sync_directory(root)
        _point("area:durable")
        try:
            original = leases.private_stat(database)
            _point("checkpoint:before")
            _consolidate(database, storage_key)
            _point("checkpoint:after")
            old = _read(database)
            _durable_new(area / "rollback.sqlite3", old, "rollback")
            _durable_new(area / "rollback-ready.sqlite3", old, "rollback-ready")
            _validate_file(area / "rollback.sqlite3", storage_key)
            _validate_file(area / "rollback-ready.sqlite3", storage_key)
            if storage_key is not None:
                from sealed_database import seal_snapshot
                image = seal_snapshot(image, storage_key)
            _durable_new(area / "candidate.sqlite3", image, "candidate")
            _point("suspend:before")
            _suspend(area / "candidate.sqlite3", storage_key)
            _consolidate(area / "candidate.sqlite3", storage_key)
            _point("suspend:after")
            record.update(old=_sha(old), new=_sha(_read(area / "candidate.sqlite3")))
            _check_leases(database, maintenance_fd, writer_fd)
            _record(database, record, "PREPARED")
            _point("switch:before")
            _check_leases(database, maintenance_fd, writer_fd)
            _files(database)
            _no_sidecars(database)
            current = leases.private_stat(database)
            if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                raise ActivationError("identidade do banco mudou antes da troca")
            if _sha(_read(database)) != record["old"]:
                raise ActivationError("identidade do banco mudou antes da troca")
            os.replace(area / "candidate.sqlite3", database)
            _point("switch:after")
            leases.sync_directory(database.parent)
            leases.sync_directory(area)
            _point("switch:durable")
            _record(database, record, "SWITCHED")
            _validate_file(database, storage_key)
            if _sha(_read(database)) != record["new"]:
                raise ActivationError("imagem ativada divergiu")
            _point("validation:after")
            _record(database, record, "COMMITTED")
            return area / "rollback.sqlite3"
        except Exception as exc:
            # Preserve the durable evidence. A future exclusive startup retries
            # recovery, including when IO/fsync/rollback itself remains broken.
            raise ActivationError("ativação interrompida; recuperação offline necessária") from exc


def recover_locked(database: Path, storage_key: bytes | None = None) -> None:
    """Called BEFORE initialize/migrations, under exclusive maintenance."""
    record = _state(database)
    if record is None:
        return
    _require_origin(database)
    if record["schema"] != _schema():
        raise ActivationError("runtime incompatível com registro de ativação")
    # Legacy journal recovery remains supported for explicit legacy fixtures.
    if not _read(database).startswith(SEALED_DATABASE_MAGIC):
        storage_key = None
        _require_legacy_sqlite(database)
    if storage_key is None:
        _require_legacy_sqlite(database)
    state = record["state"]
    if state in {"COMMITTED", "ROLLED_BACK", "ABORTED"}:
        _files(database)
        _validate_file(database, storage_key)
        return
    if state == "BUILDING":
        # Replacement cannot precede a durable PREPARED record.
        _consolidate(database, storage_key)
        _record(database, record, "ABORTED")
        return
    area = _ledger(database) / record["operation"]
    leases.private_stat(area, directory=True)
    rollback = area / "rollback.sqlite3"
    if _sha(_read(rollback)) != record["old"]:
        raise ActivationError("rollback preservado inválido")
    _validate_file(rollback, storage_key)
    _consolidate(database, storage_key)
    actual = _sha(_read(database))
    if actual not in {record["old"], record["new"]}:
        raise ActivationError("banco inesperado; recuperação manual necessária")
    if actual == record["new"]:
        ready = area / "rollback-ready.sqlite3"
        if _sha(_read(ready)) != record["old"]:
            raise ActivationError("rollback pronto inválido")
        _validate_file(ready, storage_key)
        _point("rollback:before")
        _no_sidecars(database)
        os.replace(ready, database)
        _point("rollback:after")
        leases.sync_directory(database.parent)
        leases.sync_directory(area)
        _point("rollback:durable")
    # Also finish a crash after rollback rename but before its record.
    _validate_file(database, storage_key)
    if _sha(_read(database)) != record["old"]:
        raise ActivationError("rollback divergiu")
    leases.sync_directory(database.parent)
    _record(database, record, "ROLLED_BACK")


def recover_activation(database: Path | str, *, storage_key: bytes | None = None) -> None:
    database = leases.checked_path(database)
    with leases.lock(database, exclusive=True), leases.lock(database, writer=True):
        recover_locked(database, storage_key)
