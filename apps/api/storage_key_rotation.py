"""Crash-safe rotation of the synthetic sealed-database key.

The active database is the JVSDB snapshot, not a plaintext SQLite file and not
a ``.jvb`` backup. SQLite stays in process memory. Each generation is a
distinct Keychain account. The legacy account ``primary`` is never replaced
in place. The previous account is deleted only after the new snapshot has
been published, reopened and validated.

A crash at any durable step leaves at least one generation that can be
opened: the previous ciphertext until publish succeeds, and the new
ciphertext afterwards. The recovery copy stays until the journal is
committed, the new generation opens the primary, and the old account is
absent. Removing that file ends its rollback role. It is not cryptographic
erasure: ``.jvb`` backups stay sealed by the backup password and are not
rewritten. The journal is an AES-GCM record sealed with a key that is still
present. It names generations and accounts and never contains key bytes.
A missing, forged or unreadable journal fails closed. This module never
generates a substitute key and never opens a residual file as SQLite.

Memory copies are an accepted limit. ``serialize``, AES-GCM, JSON and the
SQLite loader create transient ``bytes`` copies. Zeroing the ``bytearray``
values this module owns does not erase every heap, stack, swap or crash-dump
copy, and it is not a promise of physical RAM erasure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

import database_leases as leases
from sealed_database import (
    JOURNAL_AAD,
    KEY_BYTES,
    MAGIC,
    MAX_DATABASE_BYTES,
    SQLITE_HEADER,
    KeychainUnavailable,
    PlaintextDatabaseRefused,
    SealedDatabaseError,
    configure_memory_connection,
    load_connection,
    open_record,
    open_snapshot,
    seal_record,
    seal_snapshot,
    validate_image,
    validate_key,
)

LEGACY_ACCOUNT = "primary"
_GENERATION = re.compile(r"gen-v1-[0-9a-f]{32}")
_ACCOUNT = re.compile(r"primary|gen-v1-[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_OPERATION = re.compile(r"[0-9a-f]{64}")
_PHASES = (
    "intent",
    "key_stored",
    "staged",
    "linked",
    "published",
    "validated",
    "committed",
    "finalized",
)
CRASH_POINTS = (
    "intent",
    "before_journal_key_stored",
    "key_stored",
    "before_journal_staged",
    "staged",
    "before_journal_linked",
    "linked",
    "before_journal_published",
    "published",
    "before_journal_validated",
    "validated",
    "receipt_resealed",
    "before_journal_committed",
    "committed",
    "generation_marker",
    "receipt_recorded",
    "recovery_removed",
    "before_journal_finalized",
    "finalized",
)
_JOURNAL_KEYS = (
    "from_account",
    "operation_id",
    "phase",
    "primary_digest",
    "recovery_name",
    "schema",
    "staged_digest",
    "staged_name",
    "to_account",
    "version",
)
_RECEIPT_AAD = b"jarvis-key-rotation-receipt-v1"
_RECEIPT_KEYS = ("operations", "version")
_MAX_RECEIPT_OPERATIONS = 32
_MAX_JOURNAL_PAYLOAD = 4096
_MAX_JOURNAL_FILE = 8192
_CONTAINER_LIMIT = MAX_DATABASE_BYTES + len(MAGIC) + 12 + 8 + 16


class RotationCrash(RuntimeError):
    """Injected stop after a durable transition. Carries only the point name."""


class RotationBlocked(SealedDatabaseError):
    """Fail closed. The message names the condition, never key bytes."""


class RotationAmbiguous(RotationBlocked):
    """Journal, digest or recovery evidence does not identify one generation."""


class DuplicateKeychainItem(SealedDatabaseError):
    """An existing generation item is not replaced."""


class KeychainPort(Protocol):
    def load(self, account: str) -> bytes | None: ...

    def store_new(self, account: str, key: bytes) -> None: ...

    def delete(self, account: str) -> None: ...


@dataclass
class Journal:
    phase: str
    from_account: str
    to_account: str
    operation_id: str
    primary_digest: str
    staged_digest: str
    staged_name: str
    recovery_name: str
    schema: str
    version: int = 2

    def to_json(self) -> dict[str, object]:
        return {
            "from_account": self.from_account,
            "operation_id": self.operation_id,
            "phase": self.phase,
            "primary_digest": self.primary_digest,
            "recovery_name": self.recovery_name,
            "schema": self.schema,
            "staged_digest": self.staged_digest,
            "staged_name": self.staged_name,
            "to_account": self.to_account,
            "version": self.version,
        }


@dataclass(frozen=True)
class RotationResult:
    phase: str
    from_account: str
    to_account: str
    retire_account: str
    key_changed: bool
    operation_id: str
    cleanup: str


class SuppliedKeys:
    """In-process claim that the supervisor already stored these exact items.

    ``store_new`` refuses an account that was not supplied and never replaces
    a different value. It does not talk to the macOS Keychain. The supervisor
    must persist the new generation before calling the runtime.
    """

    def __init__(self, items: dict[str, bytes]) -> None:
        self._items = {account: bytes(key) for account, key in items.items()}
        self.deleted: list[str] = []

    def load(self, account: str) -> bytes | None:
        value = self._items.get(account)
        return None if value is None else bytes(value)

    def store_new(self, account: str, key: bytes) -> None:
        current = self._items.get(account)
        if current is None:
            raise KeychainUnavailable("geração não confirmada no cofre")
        if not hmac.compare_digest(current, bytes(key)):
            raise DuplicateKeychainItem("item de geração existente não é substituído")

    def delete(self, account: str) -> None:
        self.deleted.append(account)
        self._items.pop(account, None)


def journal_path(database: Path) -> Path:
    return database.parent / f".{database.name}.key-rotation.json"


def select_account(database: Path, *keys: bytes) -> str:
    """Return the account that matches the current ciphertext. Do not mutate."""
    database = _database_path(database)
    journal = _read_journal(database, *keys)
    if journal is None:
        return LEGACY_ACCOUNT
    blob = _read_container(database)
    digest = _digest(blob)
    try:
        return _account_for_digest(journal, digest)
    except RotationAmbiguous:
        # A commit after validation publishes a new nonce. The journal digests
        # stay the crash anchors; the key that opens the current envelope is
        # the generation already validated.
        if journal.phase not in {"validated", "committed", "finalized"}:
            raise
        for key in keys:
            if not key:
                continue
            try:
                open_snapshot(blob, key)
            except (SealedDatabaseError, PlaintextDatabaseRefused):
                continue
            return journal.to_account
        raise


def operation_for(generation: str) -> str:
    """Stable id of one generation. It is not a key and not a ciphertext digest."""
    _validate_generation(generation)
    return hashlib.sha256(generation.encode("ascii")).hexdigest()


def rotate_generation(
    database: Path,
    *,
    old_key: bytes | None,
    new_key: bytes,
    generation: str,
    keychain: KeychainPort,
    operation_id: str | None = None,
    intent: str = "begin",
    crash_after: str | None = None,
    leases_held: bool = False,
    retire: bool = True,
    finalize_requested: bool = False,
    published_validator: Callable[[bytes], None] | None = None,
) -> RotationResult:
    """Advance or resume one rotation. ``crash_after`` stops after that point."""
    if crash_after is not None and crash_after not in CRASH_POINTS:
        raise RotationBlocked("ponto de interrupção desconhecido")
    if intent not in {"begin", "resume"}:
        raise RotationBlocked("intenção de rotação inválida")
    _validate_generation(generation)
    if operation_id is None:
        operation_id = operation_for(generation)
    if operation_id != operation_for(generation):
        raise RotationBlocked("operação não corresponde à geração")
    validate_key(new_key)
    if old_key is not None:
        validate_key(old_key)
    new_buf = bytearray(new_key)
    old_buf = bytearray(old_key) if old_key is not None else None
    try:
        database = _database_path(database)
        with _coordination(database, leases_held):
            return _rotate_locked(
                database,
                old_key=bytes(old_buf) if old_buf is not None else None,
                new_key=bytes(new_buf),
                generation=generation,
                operation_id=operation_id,
                intent=intent,
                keychain=keychain,
                crash_after=crash_after,
                retire=retire,
                finalize_requested=finalize_requested,
                published_validator=published_validator,
            )
    finally:
        new_buf[:] = b"\x00" * len(new_buf)
        if old_buf is not None:
            old_buf[:] = b"\x00" * len(old_buf)


def finalize_rotation(
    database: Path,
    *,
    current_key: bytes,
    operation_id: str,
    keychain: KeychainPort,
    leases_held: bool = False,
    crash_after: str | None = None,
) -> RotationResult:
    """Remove the recovery role after commit, reopen and old-key absence."""
    validate_key(current_key)
    if not _OPERATION.fullmatch(operation_id):
        raise RotationBlocked("operação de rotação inválida")
    key_buf = bytearray(current_key)
    try:
        database = _database_path(database)
        with _coordination(database, leases_held):
            journal = _require_journal(database, bytes(key_buf))
            if journal.operation_id != operation_id:
                raise RotationBlocked("operação não corresponde à rotação")
            if journal.phase == "finalized":
                _require_active_open(database, bytes(key_buf))
                return _result(journal, key_changed=False, retire_account="")
            if _account_still_present(keychain, journal.from_account):
                raise RotationBlocked("chave antiga ainda presente")
            return _rotate_locked(
                database,
                old_key=bytes(key_buf),
                new_key=bytes(key_buf),
                generation=journal.to_account,
                operation_id=operation_id,
                intent="resume",
                keychain=keychain,
                crash_after=crash_after,
                retire=False,
                finalize_requested=True,
                published_validator=None,
            )
    finally:
        key_buf[:] = b"\x00" * len(key_buf)


def mark_rotation_retired(
    database: Path,
    *,
    current_key: bytes,
    from_account: str,
    leases_held: bool = False,
) -> None:
    """Record commit after the supervisor has retired the old account."""
    validate_key(current_key)
    if not _ACCOUNT.fullmatch(from_account):
        raise RotationBlocked("conta antiga inválida")
    key_buf = bytearray(current_key)
    try:
        database = _database_path(database)
        with _coordination(database, leases_held):
            journal = _require_journal(database, bytes(key_buf))
            if journal.phase == "committed" and journal.from_account == from_account:
                _require_published(database, journal, bytes(key_buf))
                return
            if journal.phase != "validated" or journal.from_account != from_account:
                raise RotationBlocked("aposentadoria fora da fase validada")
            _require_published(database, journal, bytes(key_buf))
            journal.phase = "committed"
            _write_journal(database, journal, bytes(key_buf))
    finally:
        key_buf[:] = b"\x00" * len(key_buf)


def _rotate_locked(
    database: Path,
    *,
    old_key: bytes | None,
    new_key: bytes,
    generation: str,
    operation_id: str,
    intent: str,
    keychain: KeychainPort,
    crash_after: str | None,
    retire: bool,
    finalize_requested: bool,
    published_validator: Callable[[bytes], None] | None,
) -> RotationResult:
    _refuse_sidecars(database)
    keys = tuple(key for key in (old_key, new_key) if key)
    journal = _read_journal(database, *keys)
    completed = _completed_operations(database, *keys)
    current_cleanup = journal is not None and journal.operation_id == operation_id and journal.phase != "finalized"
    if not current_cleanup and (
        operation_id in completed
        or (journal is not None and journal.phase == "finalized" and journal.operation_id == operation_id)
    ):
        _require_active_open(database, new_key)
        return _completed_result(journal, operation_id, generation)
    if journal is not None and journal.operation_id != operation_id:
        if journal.phase != "finalized" or intent != "begin":
            raise RotationBlocked("rotação ou limpeza pendente")
        if _sealed_recoveries(database):
            raise RotationBlocked("limpeza da recuperação ainda pendente")
        _require_marker(database, journal)
    elif journal is not None:
        if journal.to_account != generation:
            raise RotationBlocked("rotação em andamento usa outra geração")
        if journal.phase == "finalized":
            _require_active_open(database, new_key)
            return _result(journal, key_changed=False, retire_account="")
        return _finish(
            database, journal, old_key, new_key, keychain, crash_after, retire,
            finalize_requested, published_validator,
        )
    elif intent != "begin":
        raise RotationBlocked("operação desconhecida")
    if _sealed_recoveries(database):
        raise RotationBlocked("limpeza da recuperação ainda pendente")
    from_account = LEGACY_ACCOUNT if journal is None else journal.to_account
    if from_account == generation:
        raise RotationBlocked("geração nova igual à atual")
    try:
        existing_new = keychain.load(generation)
    except Exception as exc:
        raise KeychainUnavailable("cofre indisponível") from exc
    if existing_new is not None and not hmac.compare_digest(existing_new, new_key):
        raise DuplicateKeychainItem("item de geração existente não é substituído")
    blob = _read_container(database)
    if old_key is None:
        raise RotationBlocked("chave antiga ausente")
    if generation != _generation_name(_digest(blob)):
        raise RotationBlocked("geração não corresponde ao ciphertext")
    _require_key_opens(keychain, from_account, old_key, blob, missing="chave antiga ausente")
    image = open_snapshot(blob, old_key)
    schema = _schema_fingerprint(image)
    journal = Journal(
        phase="intent",
        from_account=from_account,
        to_account=generation,
        operation_id=operation_id,
        primary_digest=_digest(blob),
        staged_digest="",
        staged_name="",
        recovery_name="",
        schema=schema,
    )
    _write_journal(database, journal, old_key, new_key)
    _crash(crash_after, "intent")
    return _finish(
        database, journal, old_key, new_key, keychain, crash_after, retire,
        finalize_requested, published_validator,
    )


def _finish(
    database: Path,
    journal: Journal,
    old_key: bytes | None,
    new_key: bytes,
    keychain: KeychainPort,
    crash_after: str | None,
    retire: bool,
    finalize_requested: bool,
    published_validator: Callable[[bytes], None] | None,
) -> RotationResult:
    while journal.phase != "finalized":
        _refuse_sidecars(database)
        blob = _read_container(database)
        digest = _digest(blob)
        phase = journal.phase
        if phase == "committed":
            opened_by = None
        elif digest == journal.primary_digest:
            opened_by = _require_key_opens(
                keychain, journal.from_account, old_key, blob, missing="chave antiga ausente",
            )
        elif journal.staged_digest and digest == journal.staged_digest:
            opened_by = None
            _require_key_opens(
                keychain, journal.to_account, new_key, blob, missing="chave nova ausente",
            )
        else:
            raise RotationAmbiguous("digest do primário não corresponde ao journal")
        if phase == "intent":
            _ensure_stored_new(keychain, journal.to_account, new_key, None)
            _crash(crash_after, "before_journal_key_stored")
            journal.phase = "key_stored"
            _write_journal(database, journal, old_key, new_key)
            _crash(crash_after, "key_stored")
        elif phase == "key_stored":
            if opened_by is None:
                raise RotationAmbiguous("fase anterior ao publish sem o primário antigo")
            image = open_snapshot(blob, opened_by)
            if _schema_fingerprint(image) != journal.schema:
                raise RotationBlocked("schema incompatível")
            staged_name, staged_digest = _write_sibling(
                database, seal_snapshot(image, new_key), "staged",
            )
            _crash(crash_after, "before_journal_staged")
            journal.staged_name = staged_name
            journal.staged_digest = staged_digest
            journal.phase = "staged"
            _write_journal(database, journal, old_key, new_key)
            _crash(crash_after, "staged")
        elif phase == "staged":
            _require_named_digest(database, journal.staged_name, journal.staged_digest, "staged")
            if digest != journal.primary_digest:
                raise RotationAmbiguous("cópia de recuperação exigiria o primário antigo")
            existing = _sealed_recoveries(database)
            if len(existing) > 1:
                raise RotationAmbiguous("mais de uma cópia de recuperação")
            if existing:
                adopted = _read_container(existing[0])
                if _digest(adopted) != journal.primary_digest:
                    raise RotationAmbiguous("cópia de recuperação não confere")
                recovery_name = existing[0].name
            else:
                recovery_name, _recovery_digest = _write_sibling(database, blob, "sealed")
            _crash(crash_after, "before_journal_linked")
            journal.recovery_name = recovery_name
            journal.phase = "linked"
            _write_journal(database, journal, old_key, new_key)
            _crash(crash_after, "linked")
        elif phase == "linked":
            _require_named_digest(
                database, journal.recovery_name, journal.primary_digest, "sealed",
            )
            if digest == journal.primary_digest:
                staged = _require_named_digest(
                    database, journal.staged_name, journal.staged_digest, "staged",
                )
                try:
                    image = open_snapshot(staged, new_key)
                except SealedDatabaseError as exc:
                    raise RotationBlocked("chave nova ausente") from exc
                if _schema_fingerprint(image) != journal.schema:
                    raise RotationBlocked("schema incompatível")
                _replace_primary(database, staged)
                _crash(crash_after, "before_journal_published")
            elif digest != journal.staged_digest:
                raise RotationAmbiguous("publish interrompido sem digest reconhecido")
            else:
                _crash(crash_after, "before_journal_published")
            journal.phase = "published"
            _write_journal(database, journal, old_key, new_key)
            _crash(crash_after, "published")
        elif phase == "published":
            if digest == journal.primary_digest:
                # Validation failed and the previous ciphertext was restored
                # before the journal could record the revert.
                journal.phase = "linked"
                _write_journal(database, journal, old_key, new_key)
                continue
            if digest != journal.staged_digest:
                raise RotationAmbiguous("primário publicado não confere")
            try:
                image = open_snapshot(blob, new_key)
            except SealedDatabaseError as exc:
                raise RotationBlocked("chave nova ausente") from exc
            try:
                if _schema_fingerprint(image) != journal.schema:
                    raise SealedDatabaseError("schema incompatível")
                if published_validator is not None:
                    published_validator(image)
            except SealedDatabaseError:
                _revert_to_recovery(database, journal, keychain)
                raise RotationBlocked("validação da geração nova falhou") from None
            _crash(crash_after, "before_journal_validated")
            journal.phase = "validated"
            _write_journal(database, journal, old_key, new_key)
            _crash(crash_after, "validated")
        elif phase == "validated":
            _reseal_receipt(database, old_key, new_key)
            _crash(crash_after, "receipt_resealed")
            if not retire:
                _require_published(database, journal, new_key)
                return _result(journal, key_changed=True, retire_account=journal.from_account)
            _retire_old(keychain, journal)
            _crash(crash_after, "before_journal_committed")
            journal.phase = "committed"
            _write_journal(database, journal, old_key, new_key)
            _crash(crash_after, "committed")
        elif phase == "committed":
            if _account_still_present(keychain, journal.from_account):
                if not retire:
                    if finalize_requested:
                        raise RotationBlocked("chave antiga ainda presente")
                    return _result(journal, key_changed=False, retire_account=journal.from_account)
                _retire_old(keychain, journal)
                if _account_still_present(keychain, journal.from_account):
                    raise RotationBlocked("chave antiga ainda presente")
            elif not retire and not finalize_requested:
                return _result(journal, key_changed=False, retire_account=journal.from_account)
            _require_open_generation(database, journal, new_key)
            _publish_marker(database, journal)
            _crash(crash_after, "generation_marker")
            _record_receipt(database, journal.operation_id, new_key)
            _crash(crash_after, "receipt_recorded")
            _unlink_named_recovery(database, journal)
            _crash(crash_after, "recovery_removed")
            _crash(crash_after, "before_journal_finalized")
            journal.phase = "finalized"
            _write_journal(database, journal, old_key, new_key)
            _crash(crash_after, "finalized")
        else:
            raise RotationAmbiguous("fase de rotação desconhecida")
    _require_open_generation(database, journal, new_key)
    return _result(journal, key_changed=True, retire_account="")


def _result(journal: Journal, *, key_changed: bool, retire_account: str) -> RotationResult:
    cleanup = "complete" if journal.phase == "finalized" else "pending"
    return RotationResult(
        journal.phase, journal.from_account, journal.to_account, retire_account,
        key_changed, journal.operation_id, cleanup,
    )


def _completed_result(journal: Journal | None, operation_id: str, generation: str) -> RotationResult:
    if journal is not None and journal.operation_id == operation_id:
        return _result(journal, key_changed=False, retire_account="")
    return RotationResult(
        "finalized", generation, generation, "", False, operation_id, "complete",
    )


def _ensure_stored_new(
    keychain: KeychainPort, account: str, new_key: bytes, staged: bytes | None,
) -> None:
    try:
        existing = keychain.load(account)
    except KeychainUnavailable:
        raise
    except DuplicateKeychainItem:
        raise
    except Exception as exc:
        raise KeychainUnavailable("cofre indisponível") from exc
    if existing is not None:
        if not hmac.compare_digest(existing, new_key):
            raise DuplicateKeychainItem("item de geração existente não é substituído")
        return
    if staged is not None:
        try:
            open_snapshot(staged, new_key)
        except SealedDatabaseError as exc:
            raise RotationBlocked("chave nova ausente") from exc
    try:
        keychain.store_new(account, new_key)
    except DuplicateKeychainItem:
        existing = keychain.load(account)
        if existing is None or not hmac.compare_digest(existing, new_key):
            raise DuplicateKeychainItem("item de geração existente não é substituído")
    except KeychainUnavailable:
        raise
    except Exception as exc:
        raise KeychainUnavailable("cofre indisponível") from exc


def _require_key_opens(
    keychain: KeychainPort,
    account: str,
    supplied: bytes | None,
    blob: bytes,
    *,
    missing: str,
) -> bytes:
    try:
        loaded = keychain.load(account)
    except Exception as exc:
        raise KeychainUnavailable("cofre indisponível") from exc
    if loaded is None:
        raise RotationBlocked(missing)
    if supplied is not None and not hmac.compare_digest(loaded, supplied):
        raise RotationBlocked("chave não confere com o item da geração")
    try:
        open_snapshot(blob, loaded)
    except PlaintextDatabaseRefused:
        raise
    except SealedDatabaseError as exc:
        raise RotationBlocked(missing) from exc
    return loaded


def _retire_old(keychain: KeychainPort, journal: Journal) -> None:
    if journal.from_account == journal.to_account:
        raise RotationBlocked("aposentadoria recusada")
    try:
        current = keychain.load(journal.to_account)
    except Exception as exc:
        raise KeychainUnavailable("cofre indisponível") from exc
    if current is None:
        raise RotationBlocked("chave nova ausente")
    try:
        keychain.delete(journal.from_account)
    except KeychainUnavailable:
        raise
    except Exception as exc:
        raise KeychainUnavailable("cofre indisponível") from exc


def _revert_to_recovery(database: Path, journal: Journal, keychain: KeychainPort) -> None:
    """Put the previous ciphertext back. Keep the recovery file either way."""
    try:
        recovery = _require_named_digest(
            database, journal.recovery_name, journal.primary_digest, "sealed",
        )
        old = keychain.load(journal.from_account)
        if old is None:
            raise RotationAmbiguous("reversão sem a chave antiga")
        image = open_snapshot(recovery, old)
        if _schema_fingerprint(image) != journal.schema:
            raise RotationAmbiguous("reversão com schema divergente")
    except RotationAmbiguous:
        raise
    except (SealedDatabaseError, OSError) as exc:
        raise RotationAmbiguous("cópia de recuperação inutilizável") from exc
    _replace_primary(database, recovery)
    journal.phase = "linked"
    _write_journal(database, journal, old)


def _require_published(database: Path, journal: Journal, key: bytes) -> None:
    blob = _read_container(database)
    if _digest(blob) != journal.staged_digest:
        raise RotationAmbiguous("primário não está na geração publicada")
    image = open_snapshot(blob, key)
    if _schema_fingerprint(image) != journal.schema:
        raise RotationBlocked("schema incompatível")


def _account_for_digest(journal: Journal, digest: str) -> str:
    if journal.staged_digest and journal.staged_digest == journal.primary_digest:
        if digest == journal.primary_digest:
            return journal.from_account
        raise RotationAmbiguous("journal sem geração distinta")
    if digest == journal.primary_digest:
        return journal.from_account
    if journal.staged_digest and digest == journal.staged_digest:
        return journal.to_account
    raise RotationAmbiguous("digest do primário não corresponde ao journal")


def _schema_fingerprint(image: bytes) -> str:
    validate_image(image)
    connection = sqlite3.connect(":memory:")
    try:
        load_connection(connection, image)
        configure_memory_connection(connection)
        try:
            rows = connection.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise SealedDatabaseError("schema incompatível") from exc
    finally:
        connection.close()
    files = sorted((Path(__file__).resolve().parent / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not files or not rows:
        raise SealedDatabaseError("schema incompatível")
    expected = [
        (migration.stem, hashlib.sha256(migration.read_text(encoding="utf-8").encode("utf-8")).hexdigest())
        for migration in files
    ]
    actual = [(str(row[0]), str(row[1])) for row in rows]
    if actual != expected:
        raise SealedDatabaseError("schema incompatível")
    return ",".join(version for version, _checksum in actual)


def _generation_name(digest: str) -> str:
    return "gen-v1-" + digest[:32]


def _account_still_present(keychain: KeychainPort, account: str) -> bool:
    try:
        return keychain.load(account) is not None
    except Exception as exc:
        raise KeychainUnavailable("cofre indisponível") from exc


def _require_active_open(database: Path, key: bytes) -> None:
    open_snapshot(_read_container(database), key)


def _require_open_generation(database: Path, journal: Journal, key: bytes) -> None:
    blob = _read_container(database)
    if _digest(blob) == journal.primary_digest:
        raise RotationAmbiguous("primário ainda está na geração anterior")
    image = open_snapshot(blob, key)
    if _schema_fingerprint(image) != journal.schema:
        raise RotationBlocked("schema incompatível")


def _sealed_recoveries(database: Path) -> list[Path]:
    prefix = f".{database.name}.rotation-"
    found: list[Path] = []
    for entry in database.parent.iterdir():
        if not entry.name.startswith(prefix) or not entry.name.endswith(".sealed"):
            continue
        if entry.is_symlink() or not entry.is_file():
            raise RotationAmbiguous("cópia de recuperação insegura")
        found.append(entry)
    return found


def _marker_path(database: Path) -> Path:
    return database.parent / f".{database.name}.key-generation"


def _read_marker(database: Path) -> tuple[str, str] | None:
    path = _marker_path(database)
    if not path.exists() and not path.is_symlink():
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RotationAmbiguous("marcador de geração inseguro") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_nlink != 1
            or info.st_size > 128
        ):
            raise RotationAmbiguous("marcador de geração inseguro")
        raw = os.read(fd, 129)
    finally:
        os.close(fd)
    try:
        text = raw.decode("ascii", errors="strict")
        account, operation_id, extra = text.split("\n", 2)
    except (UnicodeError, ValueError) as exc:
        raise RotationAmbiguous("marcador de geração incompatível") from exc
    if extra or not _GENERATION.fullmatch(account) or operation_id != operation_for(account):
        raise RotationAmbiguous("marcador de geração incompatível")
    return account, operation_id


def _require_marker(database: Path, journal: Journal) -> None:
    marker = _read_marker(database)
    if marker != (journal.to_account, journal.operation_id):
        raise RotationAmbiguous("marcador de geração ausente")


def _publish_marker(database: Path, journal: Journal) -> None:
    current = _read_marker(database)
    expected = (journal.to_account, journal.operation_id)
    if current == expected:
        return
    if current is not None and current[0] not in {journal.from_account, journal.to_account}:
        raise RotationAmbiguous("marcador de geração divergente")
    payload = f"{journal.to_account}\n{journal.operation_id}\n".encode("ascii")
    temporary = database.parent / f".{database.name}.key-generation-{secrets.token_hex(8)}.tmp"
    _write_exclusive(temporary, payload)
    os.replace(temporary, _marker_path(database))
    leases.sync_directory(database.parent)


def _receipt_path(database: Path) -> Path:
    return database.parent / f".{database.name}.key-rotation-receipts"


def _completed_operations(database: Path, *keys: bytes | None) -> set[str]:
    path = _receipt_path(database)
    if not path.exists() and not path.is_symlink():
        return set()
    payload = _open_receipt(path, *keys)
    return set(payload)


def _open_receipt(path: Path, *keys: bytes | None) -> list[str]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RotationAmbiguous("recibo de rotação inseguro") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_nlink != 1
            or info.st_size > _MAX_JOURNAL_FILE
        ):
            raise RotationAmbiguous("recibo de rotação inseguro")
        raw = os.read(fd, _MAX_JOURNAL_FILE + 1)
    finally:
        os.close(fd)
    payload_bytes: bytes | None = None
    for key in keys:
        if not key:
            continue
        try:
            payload_bytes = open_record(raw, key, _RECEIPT_AAD)
            break
        except (SealedDatabaseError, PlaintextDatabaseRefused):
            continue
    if payload_bytes is None:
        raise RotationAmbiguous("recibo de rotação inválido")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RotationAmbiguous("recibo de rotação incompatível") from exc
    if not isinstance(payload, dict) or tuple(sorted(payload)) != _RECEIPT_KEYS or payload["version"] != 1:
        raise RotationAmbiguous("recibo de rotação incompatível")
    operations = payload["operations"]
    if (
        not isinstance(operations, list)
        or len(operations) > _MAX_RECEIPT_OPERATIONS
        or len(set(operations)) != len(operations)
        or any(not isinstance(item, str) or not _OPERATION.fullmatch(item) for item in operations)
    ):
        raise RotationAmbiguous("recibo de rotação incompatível")
    return operations


def _write_receipt(database: Path, operations: list[str], key: bytes) -> None:
    payload = json.dumps(
        {"operations": operations, "version": 1}, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    blob = seal_record(payload, key, _RECEIPT_AAD)
    temporary = database.parent / f".{database.name}.key-rotation-receipts-{secrets.token_hex(8)}.tmp"
    _write_exclusive(temporary, blob)
    os.replace(temporary, _receipt_path(database))
    leases.sync_directory(database.parent)


def _reseal_receipt(database: Path, old_key: bytes | None, new_key: bytes) -> None:
    path = _receipt_path(database)
    if not path.exists() and not path.is_symlink():
        return
    operations = _open_receipt(path, new_key, old_key)
    _write_receipt(database, operations, new_key)


def _record_receipt(database: Path, operation_id: str, key: bytes) -> None:
    path = _receipt_path(database)
    operations = [] if not path.exists() and not path.is_symlink() else _open_receipt(path, key)
    if operation_id in operations:
        return
    if len(operations) >= _MAX_RECEIPT_OPERATIONS:
        raise RotationBlocked("recibo de rotação cheio")
    operations.append(operation_id)
    _write_receipt(database, operations, key)


def _unlink_named_recovery(database: Path, journal: Journal) -> None:
    named = _named_sibling(database, journal.recovery_name, "sealed")
    extras = [item for item in _sealed_recoveries(database) if item.name != journal.recovery_name]
    if extras:
        raise RotationAmbiguous("mais de uma cópia de recuperação")
    if not named.exists():
        return
    blob = _read_container(named)
    if _digest(blob) != journal.primary_digest:
        raise RotationAmbiguous("arquivo nomeado não confere com o journal")
    if named.name == database.name:
        raise RotationBlocked("limpeza recusou o banco ativo")
    os.unlink(named)
    leases.sync_directory(database.parent)


def _write_sibling(database: Path, blob: bytes, kind: str) -> tuple[str, str]:
    if not blob.startswith(MAGIC):
        raise RotationBlocked("escrita recusou conteúdo sem envelope")
    name = f".{database.name}.rotation-{secrets.token_hex(12)}.{kind}"
    target = database.parent / name
    _write_exclusive(target, blob)
    leases.sync_directory(database.parent)
    return name, _digest(blob)


def _replace_primary(database: Path, source: bytes) -> None:
    if not source.startswith(MAGIC) or source.startswith(SQLITE_HEADER):
        raise RotationBlocked("publicação recusou conteúdo sem envelope")
    temporary = database.parent / f".{database.name}.rotation-{secrets.token_hex(12)}.staged"
    _write_exclusive(temporary, source)
    os.replace(temporary, database)
    leases.sync_directory(database.parent)


def _require_named_digest(database: Path, name: str, digest: str, kind: str) -> bytes:
    path = _named_sibling(database, name, kind)
    blob = _read_container(path)
    if _digest(blob) != digest:
        raise RotationAmbiguous("arquivo nomeado não confere com o journal")
    return blob


def _named_sibling(database: Path, name: str, kind: str) -> Path:
    prefix = f".{database.name}.rotation-"
    if (
        not name
        or name != Path(name).name
        or not name.startswith(prefix)
        or not name.endswith(f".{kind}")
        or "/" in name
        or "\\" in name
    ):
        raise RotationAmbiguous("nome de recuperação inválido")
    return database.parent / name


def _read_journal(database: Path, *keys: bytes | None) -> Journal | None:
    path = journal_path(database)
    if not path.exists() and not path.is_symlink():
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RotationAmbiguous("journal de rotação inseguro") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_nlink != 1
            or info.st_size > _MAX_JOURNAL_FILE
        ):
            raise RotationAmbiguous("journal de rotação inseguro")
        raw = os.read(fd, _MAX_JOURNAL_FILE + 1)
    finally:
        os.close(fd)
    if len(raw) > _MAX_JOURNAL_FILE or raw.startswith(SQLITE_HEADER):
        raise RotationAmbiguous("journal de rotação inseguro")
    payload_bytes: bytes | None = None
    for key in keys:
        if not key:
            continue
        try:
            payload_bytes = open_record(raw, key, JOURNAL_AAD)
            break
        except (SealedDatabaseError, PlaintextDatabaseRefused):
            continue
    if payload_bytes is None:
        raise RotationAmbiguous("journal de rotação inválido")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RotationAmbiguous("journal de rotação incompatível") from exc
    if not isinstance(payload, dict) or tuple(sorted(payload)) != _JOURNAL_KEYS:
        raise RotationAmbiguous("journal de rotação incompatível")
    if payload["version"] != 2 or payload["phase"] not in _PHASES:
        raise RotationAmbiguous("journal de rotação incompatível")
    journal = Journal(
        phase=str(payload["phase"]),
        from_account=str(payload["from_account"]),
        to_account=str(payload["to_account"]),
        operation_id=str(payload["operation_id"]),
        primary_digest=str(payload["primary_digest"]),
        staged_digest=str(payload["staged_digest"]),
        staged_name=str(payload["staged_name"]),
        recovery_name=str(payload["recovery_name"]),
        schema=str(payload["schema"]),
    )
    _validate_journal_shape(journal)
    return journal


def _require_journal(database: Path, *keys: bytes | None) -> Journal:
    journal = _read_journal(database, *keys)
    if journal is None:
        raise RotationBlocked("journal de rotação ausente")
    return journal


def _validate_journal_shape(journal: Journal) -> None:
    if not _ACCOUNT.fullmatch(journal.from_account) or not _GENERATION.fullmatch(journal.to_account):
        raise RotationAmbiguous("journal de rotação incompatível")
    if journal.operation_id != operation_for(journal.to_account):
        raise RotationAmbiguous("journal de rotação incompatível")
    if journal.from_account == journal.to_account or not _DIGEST.fullmatch(journal.primary_digest):
        raise RotationAmbiguous("journal de rotação incompatível")
    if journal.staged_digest and not _DIGEST.fullmatch(journal.staged_digest):
        raise RotationAmbiguous("journal de rotação incompatível")
    if journal.phase in {"intent", "key_stored"} and (journal.staged_digest or journal.staged_name):
        raise RotationAmbiguous("journal de rotação incompatível")
    if journal.phase in {"staged", "linked", "published", "validated", "committed", "finalized"} and (
        not journal.staged_digest or not journal.staged_name
    ):
        raise RotationAmbiguous("journal de rotação incompatível")
    if journal.phase in {"linked", "published", "validated", "committed", "finalized"} and not journal.recovery_name:
        raise RotationAmbiguous("journal de rotação incompatível")
    if not journal.schema or any(char in journal.schema for char in "\n/\\"):
        raise RotationAmbiguous("journal de rotação incompatível")


def _journal_seal_key(journal: Journal, keys: tuple[bytes | None, ...]) -> bytes:
    usable = [key for key in keys if key]
    if not usable:
        raise RotationBlocked("journal de rotação sem chave de autenticação")
    if journal.phase in {"published", "validated", "committed", "finalized"}:
        return usable[-1]
    return usable[0]


def _write_journal(database: Path, journal: Journal, *keys: bytes | None) -> None:
    _validate_journal_shape(journal)
    payload = json.dumps(journal.to_json(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_JOURNAL_PAYLOAD:
        raise RotationBlocked("journal de rotação excede o limite")
    blob = seal_record(payload, _journal_seal_key(journal, keys), JOURNAL_AAD)
    temporary = database.parent / f".{database.name}.key-rotation-{secrets.token_hex(8)}.tmp"
    _write_exclusive(temporary, blob)
    os.replace(temporary, journal_path(database))
    leases.sync_directory(database.parent)


def _write_exclusive(path: Path, blob: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(blob)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("gravação incompleta")
            view = view[count:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        raise
    else:
        os.close(fd)


def _read_container(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RotationBlocked("arquivo de banco inseguro") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_nlink != 1
            or info.st_size > _CONTAINER_LIMIT
        ):
            raise RotationBlocked("arquivo de banco inseguro")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, _CONTAINER_LIMIT + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _CONTAINER_LIMIT:
                raise RotationBlocked("arquivo de banco inseguro")
        blob = b"".join(chunks)
    finally:
        os.close(fd)
    if blob.startswith(SQLITE_HEADER):
        raise PlaintextDatabaseRefused("banco SQLite preexistente sem cifra recusado")
    if not blob.startswith(MAGIC):
        raise RotationBlocked("snapshot cifrado inválido")
    return blob


def _refuse_sidecars(database: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        residual = Path(f"{database}{suffix}")
        if residual.exists() or residual.is_symlink():
            raise RotationBlocked("arquivo SQLite auxiliar residual; manutenção necessária")


def _database_path(database: Path) -> Path:
    database = leases.checked_path(database)
    temporary = Path(tempfile.gettempdir()).resolve()
    try:
        database.parent.resolve().relative_to(temporary)
    except ValueError as exc:
        raise RotationBlocked("rotação só aceita banco sintético temporário") from exc
    parent = database.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RotationBlocked("diretório do banco precisa ser privado")
    if database.is_symlink():
        raise RotationBlocked("arquivo de banco inseguro")
    return database


@contextmanager
def _coordination(database: Path, leases_held: bool) -> Iterator[None]:
    if leases_held:
        yield
        return
    with leases.lock(database, exclusive=True), leases.lock(database, writer=True):
        yield


def _validate_generation(generation: str) -> None:
    if not _GENERATION.fullmatch(generation):
        raise RotationBlocked("geração inválida")


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _crash(crash_after: str | None, point: str) -> None:
    if crash_after == point:
        raise RotationCrash(point)
