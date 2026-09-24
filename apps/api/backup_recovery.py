"""Encrypted, local-only backup and isolated restore for the SQLite memory store.

The module deliberately has no FastAPI dependency or route registration. Backup
snapshots are made with SQLite's online backup API into memory, authenticated
before restore bytes are written to disk, and published without overwriting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import sqlite3
import stat
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from memory_store import MIGRATIONS_DIR, REPOSITORY_ROOT, SQLiteMemoryStore

logger = logging.getLogger(__name__)

BACKUP_MAGIC = b"JARVISBK"
BACKUP_VERSION = 1
CIPHER_NAME = "AES-256-GCM"
KDF_NAME = "Argon2id"
KDF_PARAMETERS = {"iterations": 3, "lanes": 4, "memory_kib": 64 * 1024}
KEY_BYTES = 32
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
MAX_HEADER_BYTES = 4096
MAX_DATABASE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_DATABASE_BYTES + MAX_HEADER_BYTES + len(BACKUP_MAGIC) + 4 + TAG_BYTES
MIN_PASSPHRASE_CHARS = 16
MAX_PASSPHRASE_BYTES = 1024


class BackupError(RuntimeError):
    """Safe operational error; never includes secrets or database contents."""


class BackupFormatError(BackupError):
    pass


class BackupAuthenticationError(BackupError):
    pass


class BackupCollisionError(BackupError):
    pass


class RestoreDestinationError(BackupError):
    pass


def default_backup_directory(database_path: Path | str) -> Path:
    """Return the private sibling directory used by the supported CLI."""
    return Path(database_path).expanduser().parent / "backups"


def default_restore_directory(database_path: Path | str) -> Path:
    """Return the private, non-active restore root used by the supported CLI."""
    return Path(database_path).expanduser().parent / "restores"


def _canonical_path(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise BackupError("caminho local inválido")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return resolved
    raise BackupError("caminho local inválido")


def _directory_stat(path: Path, *, private: bool) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BackupError("diretório local indisponível") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise BackupError("diretório local inválido")
    if info.st_uid != os.getuid():
        raise BackupError("diretório local pertence a outro usuário")
    if private and stat.S_IMODE(info.st_mode) & 0o077:
        raise BackupError("diretório local precisa de permissões privadas")
    return info


def _ensure_private_directory(path: Path | str) -> Path:
    directory = _canonical_path(path)
    if directory.exists():
        _directory_stat(directory, private=True)
        return directory

    missing: list[Path] = []
    cursor = directory
    while not cursor.exists():
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            raise BackupError("diretório local indisponível")
        cursor = parent
    _directory_stat(cursor, private=False)
    for item in reversed(missing):
        try:
            item.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise BackupError("diretório local indisponível") from exc
        _directory_stat(item, private=True)
    return directory


def _private_temporary_directory(prefix: str) -> Path:
    parent = Path(tempfile.gettempdir()).resolve()
    try:
        parent.relative_to(REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        raise BackupError("diretório temporário local inválido")
    try:
        parent_info = parent.lstat()
    except OSError as exc:
        raise BackupError("diretório temporário local indisponível") from exc
    parent_mode = stat.S_IMODE(parent_info.st_mode)
    sticky_shared_temp = bool(parent_mode & stat.S_ISVTX)
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or (parent_info.st_uid != os.getuid() and not (parent_info.st_uid == 0 and sticky_shared_temp))
        or (parent_mode & 0o022 and not sticky_shared_temp)
    ):
        raise BackupError("diretório temporário local inseguro")
    try:
        directory = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
        os.chmod(directory, 0o700)
        _directory_stat(directory, private=True)
        return directory
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("não foi possível preparar área temporária privada") from exc


def _verify_private_file(path: Path | str, *, max_bytes: int) -> tuple[Path, os.stat_result]:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise BackupError("arquivo local inválido")
    resolved = _canonical_path(candidate)
    _directory_stat(resolved.parent, private=True)
    try:
        info = resolved.lstat()
    except OSError as exc:
        raise BackupError("arquivo local indisponível") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise BackupError("arquivo local inválido")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise BackupError("arquivo local precisa pertencer ao usuário e ser privado")
    if info.st_size <= 0 or info.st_size > max_bytes:
        raise BackupFormatError("arquivo de backup inválido")
    return resolved, info


def _verify_source_files(database_path: Path | str) -> Path:
    database = Path(database_path).expanduser()
    if database.is_symlink():
        raise BackupError("banco SQLite de origem indisponível ou inseguro")
    resolved = _canonical_path(database)
    try:
        _directory_stat(resolved.parent, private=True)
        info = resolved.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise BackupError("banco SQLite de origem indisponível ou inseguro")
        if info.st_size <= 0:
            raise BackupError("banco SQLite de origem indisponível ou inseguro")
        source_bytes = info.st_size
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{resolved}{suffix}")
            if sidecar.is_symlink():
                raise BackupError("banco SQLite de origem indisponível ou inseguro")
            try:
                sidecar_info = sidecar.lstat()
            except FileNotFoundError:
                continue
            if (
                not stat.S_ISREG(sidecar_info.st_mode)
                or sidecar_info.st_uid != os.getuid()
                or stat.S_IMODE(sidecar_info.st_mode) & 0o077
            ):
                raise BackupError("banco SQLite de origem indisponível ou inseguro")
            if suffix in {"-wal", "-journal"}:
                source_bytes += sidecar_info.st_size
        if source_bytes > MAX_DATABASE_BYTES:
            raise BackupFormatError("banco SQLite excede o limite de backup")
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("banco SQLite de origem indisponível ou inseguro") from exc
    return resolved


def _password_bytes(passphrase: str) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < MIN_PASSPHRASE_CHARS:
        raise BackupError("a senha do backup precisa ter pelo menos 16 caracteres")
    try:
        encoded = passphrase.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise BackupError("senha do backup inválida") from exc
    if len(encoded) > MAX_PASSPHRASE_BYTES:
        raise BackupError("senha do backup inválida")
    return encoded


def _derive_key(passphrase: bytes, salt: bytes) -> bytes:
    return Argon2id(
        salt=salt,
        length=KEY_BYTES,
        iterations=KDF_PARAMETERS["iterations"],
        lanes=KDF_PARAMETERS["lanes"],
        memory_cost=KDF_PARAMETERS["memory_kib"],
    ).derive(passphrase)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _seal_snapshot(snapshot: bytes, passphrase: str) -> bytes:
    password = _password_bytes(passphrase)
    if not snapshot or len(snapshot) > MAX_DATABASE_BYTES:
        raise BackupError("snapshot SQLite excede o limite permitido")
    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    header = {
        "cipher": CIPHER_NAME,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": "jarvis-sqlite-backup",
        "kdf": KDF_NAME,
        "kdf_parameters": KDF_PARAMETERS,
        "nonce": nonce.hex(),
        "salt": salt.hex(),
        "snapshot_bytes": len(snapshot),
        "version": BACKUP_VERSION,
    }
    header_bytes = _canonical_json(header)
    if len(header_bytes) > MAX_HEADER_BYTES:
        raise BackupError("cabeçalho de backup inválido")
    prefix = BACKUP_MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
    key = _derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, snapshot, prefix)
    return prefix + ciphertext


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_header(header_bytes: bytes) -> tuple[dict[str, Any], bytes, bytes]:
    try:
        header = json.loads(header_bytes.decode("ascii"), object_pairs_hook=_strict_object)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise BackupFormatError("formato de backup não reconhecido") from exc
    if not isinstance(header, dict) or _canonical_json(header) != header_bytes:
        raise BackupFormatError("formato de backup não reconhecido")
    expected_keys = {
        "cipher", "created_at", "format", "kdf", "kdf_parameters", "nonce",
        "salt", "snapshot_bytes", "version",
    }
    if set(header) != expected_keys:
        raise BackupFormatError("formato de backup não reconhecido")
    if (
        header["format"] != "jarvis-sqlite-backup"
        or type(header["version"]) is not int
        or header["version"] != BACKUP_VERSION
        or header["cipher"] != CIPHER_NAME
        or header["kdf"] != KDF_NAME
        or not isinstance(header["kdf_parameters"], dict)
        or set(header["kdf_parameters"]) != {"iterations", "lanes", "memory_kib"}
        or any(type(value) is not int for value in header["kdf_parameters"].values())
        or header["kdf_parameters"] != KDF_PARAMETERS
        or type(header["snapshot_bytes"]) is not int
        or not 1 <= header["snapshot_bytes"] <= MAX_DATABASE_BYTES
        or not isinstance(header["created_at"], str)
        or len(header["created_at"]) > 64
    ):
        raise BackupFormatError("formato ou parâmetros de backup incompatíveis")
    try:
        created = datetime.fromisoformat(header["created_at"])
        salt = bytes.fromhex(header["salt"])
        nonce = bytes.fromhex(header["nonce"])
    except (TypeError, ValueError) as exc:
        raise BackupFormatError("cabeçalho de backup inválido") from exc
    if created.tzinfo is None or len(salt) != SALT_BYTES or len(nonce) != NONCE_BYTES:
        raise BackupFormatError("cabeçalho de backup inválido")
    if salt.hex() != header["salt"] or nonce.hex() != header["nonce"]:
        raise BackupFormatError("cabeçalho de backup inválido")
    return header, salt, nonce


def _open_archive(archive: bytes, passphrase: str) -> bytes:
    password = _password_bytes(passphrase)
    if len(archive) < len(BACKUP_MAGIC) + 4 + TAG_BYTES or len(archive) > MAX_ARCHIVE_BYTES:
        raise BackupFormatError("arquivo de backup inválido")
    if archive[:len(BACKUP_MAGIC)] != BACKUP_MAGIC:
        raise BackupFormatError("formato de backup não reconhecido")
    header_length = struct.unpack(">I", archive[len(BACKUP_MAGIC):len(BACKUP_MAGIC) + 4])[0]
    if not 1 <= header_length <= MAX_HEADER_BYTES:
        raise BackupFormatError("cabeçalho de backup inválido")
    header_start = len(BACKUP_MAGIC) + 4
    ciphertext_start = header_start + header_length
    if ciphertext_start + TAG_BYTES > len(archive):
        raise BackupFormatError("arquivo de backup truncado")
    header_bytes = archive[header_start:ciphertext_start]
    header, salt, nonce = _parse_header(header_bytes)
    ciphertext = archive[ciphertext_start:]
    if len(ciphertext) != header["snapshot_bytes"] + TAG_BYTES:
        raise BackupFormatError("arquivo de backup truncado ou inconsistente")
    prefix = archive[:ciphertext_start]
    try:
        plaintext = AESGCM(_derive_key(password, salt)).decrypt(nonce, ciphertext, prefix)
    except (InvalidTag, ValueError, MemoryError) as exc:
        raise BackupAuthenticationError("senha incorreta ou backup inválido") from exc
    if len(plaintext) != header["snapshot_bytes"]:
        raise BackupAuthenticationError("senha incorreta ou backup inválido")
    return plaintext


def _expected_migration_checksums(migrations_dir: Path) -> list[tuple[str, str]]:
    files = sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not files:
        raise BackupError("migrações locais indisponíveis")
    return [(item.stem, hashlib.sha256(item.read_bytes()).hexdigest()) for item in files]


def _validate_snapshot(connection: sqlite3.Connection, validator_path: Path) -> None:
    try:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("integridade do banco restaurado inválida")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupError("integridade referencial do banco restaurado inválida")
        migration_rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        if migration_rows != _expected_migration_checksums(MIGRATIONS_DIR):
            raise BackupError("histórico de migrações do banco restaurado inválido")
        validator = SQLiteMemoryStore(validator_path)
        validator._validate_schema(connection)
    except BackupError:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        raise BackupError("integridade ou esquema do banco restaurado inválido") from exc


def _snapshot_database(database_path: Path) -> bytes:
    uri = database_path.as_uri() + "?mode=ro"
    source: sqlite3.Connection | None = None
    snapshot: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        source.execute("PRAGMA query_only=ON")
        snapshot = sqlite3.connect(":memory:", isolation_level=None)
        source.backup(snapshot, pages=128, sleep=0.01)
        _validate_snapshot(snapshot, database_path)
        image = snapshot.serialize()
        if not isinstance(image, bytes) or not image or len(image) > MAX_DATABASE_BYTES:
            raise BackupError("snapshot SQLite excede o limite permitido")
        return image
    except BackupError:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError, MemoryError) as exc:
        raise BackupError("não foi possível criar um snapshot SQLite consistente") from exc
    finally:
        if snapshot is not None:
            snapshot.close()
        if source is not None:
            source.close()


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_no_replace(source: Path, destination: Path) -> None:
    os.link(source, destination, follow_symlinks=False)


def _valid_basename(name: str, *, suffix: str) -> bool:
    return (
        isinstance(name, str)
        and 1 <= len(name) <= 160
        and name not in {".", ".."}
        and Path(name).name == name
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
        and name.endswith(suffix)
        and not name.startswith(".")
    )


def _new_backup_filename() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"jarvis-backup-v1-{now}-{secrets.token_hex(8)}.jvb"


def _new_restore_directory_name() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"restore-v1-{now}-{secrets.token_hex(8)}"


def create_backup(
    database_path: Path | str,
    backup_directory: Path | str,
    passphrase: str,
    *,
    filename: str | None = None,
) -> Path:
    """Create an authenticated encrypted snapshot without writing to the source."""
    temporary_path: Path | None = None
    temporary_fd: int | None = None
    try:
        _password_bytes(passphrase)
        source_path = _verify_source_files(database_path)
        destination_directory = _ensure_private_directory(backup_directory)
        if destination_directory == source_path.parent:
            raise BackupError("diretório de backup deve ser separado do banco")
        snapshot = _snapshot_database(source_path)
        archive = _seal_snapshot(snapshot, passphrase)
        final_name = filename or _new_backup_filename()
        if (
            not _valid_basename(final_name, suffix=".jvb")
            or not final_name.startswith("jarvis-backup-v1-")
        ):
            raise BackupError("nome de backup inválido")
        final_path = destination_directory / final_name
        temporary_fd, raw_temporary = tempfile.mkstemp(
            prefix=".jarvis-backup-", suffix=".partial", dir=destination_directory
        )
        temporary_path = Path(raw_temporary)
        os.fchmod(temporary_fd, 0o600)
        _write_all(temporary_fd, archive)
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        try:
            _publish_no_replace(temporary_path, final_path)
        except FileExistsError as exc:
            raise BackupCollisionError("backup com esse nome já existe") from exc
        try:
            _fsync_directory(destination_directory)
        except OSError as exc:
            try:
                final_path.unlink()
            except OSError:
                pass
            raise BackupError("não foi possível publicar o backup com segurança") from exc
        return final_path
    except BackupError:
        raise
    except Exception as exc:
        logger.error("encrypted backup creation failed")
        raise BackupError("não foi possível criar backup cifrado") from exc
    finally:
        if temporary_fd is not None:
            try:
                os.close(temporary_fd)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("private backup temporary file cleanup failed")


def _read_backup_file(path: Path | str) -> tuple[Path, bytes]:
    resolved, info = _verify_private_file(path, max_bytes=MAX_ARCHIVE_BYTES)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(resolved, flags)
    except OSError as exc:
        raise BackupError("arquivo de backup indisponível") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_ino != info.st_ino or opened.st_dev != info.st_dev:
            raise BackupError("arquivo de backup alterado durante a leitura")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, MAX_ARCHIVE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise BackupFormatError("arquivo de backup excede o limite")
        return resolved, b"".join(chunks)
    except OSError as exc:
        raise BackupError("não foi possível ler o backup") from exc
    finally:
        os.close(fd)


def _validate_snapshot_image(image: bytes) -> bytes:
    if not image or len(image) > MAX_DATABASE_BYTES:
        raise BackupFormatError("conteúdo SQLite do backup inválido")
    # A serialized SQLite image may retain WAL mode in its header. SQLite's
    # deserialize() cannot reliably open that image as an in-memory database;
    # validate it as a private temporary file after authentication instead.
    validation_directory = _private_temporary_directory(".jarvis-validate-")
    validation_file = validation_directory / "memory.sqlite3"
    try:
        _write_private_database(validation_file, image)
        _validate_database_file(validation_file)
        with validation_file.open("rb") as database_file:
            verified_image = database_file.read(MAX_DATABASE_BYTES + 1)
        if not verified_image or len(verified_image) > MAX_DATABASE_BYTES:
            raise BackupFormatError("conteúdo SQLite do backup inválido")
        return verified_image
    except BackupError:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError, MemoryError) as exc:
        raise BackupFormatError("conteúdo SQLite do backup inválido") from exc
    finally:
        try:
            shutil.rmtree(validation_directory)
        except OSError:
            logger.warning("private validation snapshot cleanup failed")


def _write_private_database(path: Path, image: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, image)
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove_private_sqlite_sidecars(database_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{database_path}{suffix}")
        try:
            info = sidecar.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BackupError("arquivo temporário SQLite indisponível") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise BackupError("arquivo temporário SQLite inseguro")
        try:
            sidecar.unlink()
        except OSError as exc:
            raise BackupError("não foi possível limpar arquivos temporários SQLite") from exc


def _validate_database_file(path: Path) -> None:
    uri = path.as_uri() + "?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA query_only=ON")
        _validate_snapshot(connection, path)
    except BackupError:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        raise BackupError("banco restaurado não passou na validação") from exc
    finally:
        if connection is not None:
            connection.close()


def restore_backup(
    backup_path: Path | str,
    restore_root: Path | str,
    passphrase: str,
    *,
    destination_name: str | None = None,
) -> Path:
    """Authenticate, validate, and publish a new isolated database directory."""
    staging_directory: Path | None = None
    destination_directory: Path | None = None
    destination_created = False
    restore_completed = False
    published_database: Path | None = None
    try:
        _password_bytes(passphrase)
        _, archive = _read_backup_file(backup_path)
        plaintext = _open_archive(archive, passphrase)
        name = destination_name or _new_restore_directory_name()
        if not _valid_basename(name, suffix="") or name.startswith("restore-v1-") is False:
            raise RestoreDestinationError("nome do diretório de restauração inválido")
        root = _canonical_path(restore_root)
        try:
            root.relative_to(REPOSITORY_ROOT)
        except ValueError:
            pass
        else:
            raise RestoreDestinationError("destino de restauração inválido")
        destination_directory = root / name
        if destination_directory.exists() or destination_directory.is_symlink():
            raise RestoreDestinationError("o destino de restauração já existe")
        verified_image = _validate_snapshot_image(plaintext)

        root = _ensure_private_directory(root)
        if destination_directory.exists() or destination_directory.is_symlink():
            raise RestoreDestinationError("o destino de restauração já existe")
        staging_directory = Path(tempfile.mkdtemp(prefix=".jarvis-restore-incomplete-", dir=root))
        os.chmod(staging_directory, 0o700)
        staging_file = staging_directory / "memory.sqlite3.partial"
        _write_private_database(staging_file, verified_image)
        _validate_database_file(staging_file)

        try:
            destination_directory.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise RestoreDestinationError("o destino de restauração já existe") from exc
        destination_created = True
        _directory_stat(destination_directory, private=True)
        published_database = destination_directory / "memory.sqlite3"
        os.link(staging_file, published_database, follow_symlinks=False)
        _fsync_directory(destination_directory)
        _fsync_directory(root)
        _remove_private_sqlite_sidecars(staging_file)
        staging_file.unlink()
        _fsync_directory(staging_directory)
        staging_directory.rmdir()
        staging_directory = None
        _fsync_directory(root)
        restore_completed = True
        return published_database
    except BackupError:
        raise
    except Exception as exc:
        logger.error("isolated backup restore failed")
        raise BackupError("não foi possível restaurar o backup isolado") from exc
    finally:
        if staging_directory is not None:
            try:
                shutil.rmtree(staging_directory)
            except OSError:
                logger.warning("private restore staging cleanup failed")
        if destination_created and not restore_completed and destination_directory is not None:
            if published_database is not None:
                try:
                    published_database.unlink(missing_ok=True)
                except OSError:
                    logger.warning("private restored database cleanup failed")
            try:
                destination_directory.rmdir()
            except OSError:
                logger.warning("private restore directory cleanup failed")
