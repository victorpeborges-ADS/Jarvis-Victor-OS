"""Encrypted on-disk snapshots for a SQLite database that lives only in RAM.

The primary file is an authenticated AES-256-GCM container, not a SQLite file.
SQLite connections use ``:memory:`` and snapshots are serialized in process
memory before only ciphertext is atomically published to disk. The active
runtime never opens a persistent plaintext SQLite copy.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import stat
import struct
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"JVSDB\x00\x01\x00"
KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
MAX_DATABASE_BYTES = 256 * 1024 * 1024
SQLITE_HEADER = b"SQLite format 3\x00"
_AAD = b"jarvis-active-sqlite-snapshot-v1"
JOURNAL_AAD = b"jarvis-key-rotation-journal-v1"
_JOURNAL_MAGIC = b"JVRJT\x00\x01\x00"


class SealedDatabaseError(RuntimeError):
    """Safe storage error. Messages never contain a key or database content."""


class KeyMissing(SealedDatabaseError):
    pass


class KeychainUnavailable(SealedDatabaseError):
    pass


class PlaintextDatabaseRefused(SealedDatabaseError):
    pass


def validate_key(key: bytes | bytearray | memoryview) -> None:
    if not isinstance(key, (bytes, bytearray, memoryview)) or len(key) != KEY_BYTES:
        raise SealedDatabaseError("chave de armazenamento inválida")


def seal_record(payload: bytes, key: bytes | bytearray | memoryview, aad: bytes) -> bytes:
    """Authenticate a small record. The key is not written into the container."""
    validate_key(key)
    if not isinstance(payload, bytes) or not payload or len(payload) > 4096:
        raise SealedDatabaseError("journal de rotação inválido")
    if not isinstance(aad, bytes) or not aad:
        raise SealedDatabaseError("journal de rotação inválido")
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(bytes(key)).encrypt(nonce, payload, aad)
    return _JOURNAL_MAGIC + nonce + ciphertext


def open_record(container: bytes, key: bytes | bytearray | memoryview, aad: bytes) -> bytes:
    validate_key(key)
    minimum = len(_JOURNAL_MAGIC) + NONCE_BYTES + TAG_BYTES
    if not isinstance(container, bytes) or len(container) < minimum or len(container) > 4096 + minimum:
        raise SealedDatabaseError("journal de rotação inválido")
    if container.startswith(SQLITE_HEADER):
        raise PlaintextDatabaseRefused("banco SQLite preexistente sem cifra recusado")
    if not container.startswith(_JOURNAL_MAGIC):
        raise SealedDatabaseError("journal de rotação inválido")
    nonce = container[len(_JOURNAL_MAGIC):len(_JOURNAL_MAGIC) + NONCE_BYTES]
    ciphertext = container[len(_JOURNAL_MAGIC) + NONCE_BYTES:]
    try:
        payload = AESGCM(bytes(key)).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError) as exc:
        raise SealedDatabaseError("journal de rotação inválido") from exc
    if not payload:
        raise SealedDatabaseError("journal de rotação inválido")
    return payload


def seal_snapshot(snapshot: bytes, key: bytes | bytearray | memoryview) -> bytes:
    validate_key(key)
    if not isinstance(snapshot, bytes) or not snapshot or len(snapshot) > MAX_DATABASE_BYTES:
        raise SealedDatabaseError("snapshot SQLite inválido")
    if not snapshot.startswith(SQLITE_HEADER):
        raise SealedDatabaseError("snapshot SQLite inválido")
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(bytes(key)).encrypt(nonce, snapshot, _AAD)
    return MAGIC + nonce + struct.pack(">Q", len(snapshot)) + ciphertext


def open_snapshot(container: bytes, key: bytes | bytearray | memoryview) -> bytes:
    validate_key(key)
    header_bytes = len(MAGIC) + NONCE_BYTES + 8
    if not isinstance(container, bytes) or len(container) < header_bytes + TAG_BYTES:
        raise SealedDatabaseError("snapshot cifrado inválido")
    if container.startswith(SQLITE_HEADER):
        raise PlaintextDatabaseRefused("banco SQLite preexistente sem cifra recusado")
    if not container.startswith(MAGIC):
        raise SealedDatabaseError("snapshot cifrado inválido")
    nonce_start = len(MAGIC)
    nonce = container[nonce_start:nonce_start + NONCE_BYTES]
    size_start = nonce_start + NONCE_BYTES
    expected_size = struct.unpack(">Q", container[size_start:size_start + 8])[0]
    ciphertext = container[size_start + 8:]
    if not 1 <= expected_size <= MAX_DATABASE_BYTES or len(ciphertext) != expected_size + TAG_BYTES:
        raise SealedDatabaseError("snapshot cifrado inválido")
    try:
        image = AESGCM(bytes(key)).decrypt(nonce, ciphertext, _AAD)
    except (InvalidTag, ValueError) as exc:
        raise SealedDatabaseError("não foi possível desbloquear o banco") from exc
    if len(image) != expected_size or not image.startswith(SQLITE_HEADER):
        raise SealedDatabaseError("snapshot cifrado inválido")
    return image


def read_encrypted_snapshot(path: Path, key: bytes | bytearray | memoryview) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise KeyMissing("banco cifrado ausente") from exc
    except OSError as exc:
        raise SealedDatabaseError("arquivo de banco inseguro") from exc
    try:
        info = os.fstat(fd)
        maximum = MAX_DATABASE_BYTES + len(MAGIC) + NONCE_BYTES + 8 + TAG_BYTES
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1
                or info.st_size > maximum):
            raise SealedDatabaseError("arquivo de banco inseguro")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise SealedDatabaseError("arquivo de banco inseguro")
        blob = b"".join(chunks)
    finally:
        os.close(fd)
    if blob.startswith(SQLITE_HEADER):
        raise PlaintextDatabaseRefused("banco SQLite preexistente sem cifra recusado")
    return open_snapshot(blob, key)


def inspect_pending_snapshots(path: Path, key: bytes | bytearray | memoryview) -> tuple[Path, ...]:
    """Validate crash leftovers without deleting or opening them as SQLite."""
    residues: list[Path] = []
    maximum = MAX_DATABASE_BYTES + len(MAGIC) + NONCE_BYTES + 8 + TAG_BYTES
    for candidate in path.parent.glob(f".{path.name}.cipher-*.pending"):
        try:
            fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise SealedDatabaseError("resíduo cifrado inseguro") from exc
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1
                    or info.st_size > maximum):
                raise SealedDatabaseError("resíduo cifrado inseguro")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(1024 * 1024, maximum + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum:
                    raise SealedDatabaseError("resíduo cifrado inseguro")
            residue = b"".join(chunks)
        finally:
            os.close(fd)
        if not residue.startswith(MAGIC):
            raise SealedDatabaseError("resíduo sem envelope cifrado recusado")
        minimum = len(MAGIC) + NONCE_BYTES + 8 + TAG_BYTES
        if len(residue) >= minimum:
            # A fully written crash residue must authenticate. A shorter file
            # is a ciphertext fragment from an interrupted write and is never
            # opened by SQLite or removed automatically.
            open_snapshot(residue, key)
        residues.append(candidate)
    return tuple(residues)


def write_encrypted_snapshot(
    path: Path,
    snapshot: bytes,
    key: bytes | bytearray | memoryview,
    *,
    replace: bool,
) -> None:
    """Publish ciphertext only. A crash leaves old data or ciphertext residue."""
    blob = seal_snapshot(snapshot, key)
    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = parent.stat()
    if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) & 0o077:
        raise SealedDatabaseError("diretório do banco precisa ser privado")
    if path.is_symlink():
        raise SealedDatabaseError("arquivo de banco inseguro")
    if path.exists():
        info = path.lstat()
        if (not replace or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1):
            raise SealedDatabaseError("arquivo de banco inseguro")
    temporary = parent / f".{path.name}.cipher-{secrets.token_hex(12)}.pending"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
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
    try:
        if replace and path.exists():
            os.replace(temporary, path)
        else:
            # link() gives first creation no-replace semantics on the same volume.
            os.link(temporary, path, follow_symlinks=False)
            temporary.unlink()
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # Never remove a leftover: after a crash it is ciphertext, and ownership
        # by another process cannot be ruled out by pathname inspection alone.
        raise


def load_connection(connection: sqlite3.Connection, image: bytes) -> None:
    if not image.startswith(SQLITE_HEADER) or len(image) > MAX_DATABASE_BYTES:
        raise SealedDatabaseError("snapshot SQLite inválido")
    connection.deserialize(image)


def configure_memory_connection(connection: sqlite3.Connection) -> None:
    """Disable every SQLite disk-backed spill path for the active connection."""
    connection.execute("PRAGMA journal_mode=MEMORY")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA mmap_size=0")
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA wal_autocheckpoint=0")


def validate_image(image: bytes) -> None:
    if not image.startswith(SQLITE_HEADER) or len(image) > MAX_DATABASE_BYTES:
        raise SealedDatabaseError("snapshot SQLite inválido")
    connection = sqlite3.connect(":memory:")
    try:
        load_connection(connection, image)
        configure_memory_connection(connection)
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise SealedDatabaseError("snapshot SQLite corrompido")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SealedDatabaseError("integridade referencial inválida")
    except sqlite3.DatabaseError as exc:
        raise SealedDatabaseError("snapshot SQLite inválido") from exc
    finally:
        connection.close()
