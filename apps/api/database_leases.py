"""Local advisory leases. Lock inodes are permanent; never unlink them.

Only databases born under this protocol are eligible for activation. Same-UID
software deliberately bypassing the protocol is outside this boundary.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path


class LeaseError(RuntimeError):
    pass


def checked_path(path: Path | str) -> Path:
    path = Path(path).expanduser().absolute()
    if ".." in path.parts:
        raise LeaseError("caminho de manutenção inválido")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise LeaseError("links simbólicos não são permitidos na manutenção")
    root = Path(__file__).resolve().parents[2]
    if path.is_relative_to(root):
        raise LeaseError("banco de manutenção deve ficar fora do repositório")
    return path


def private_stat(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not valid or info.st_uid != os.getuid() or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)):
        raise LeaseError("arquivo ou diretório de manutenção inseguro")
    return info


def names(database: Path) -> tuple[Path, Path, Path, Path]:
    stem = database.parent / ("." + database.name)
    return tuple(Path(str(stem) + suffix) for suffix in (
        ".maintenance.lock", ".writer.lock", ".lease-origin.json", ".activation"
    ))


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def lock(database: Path, *, exclusive: bool = False, writer: bool = False):
    database = checked_path(database)
    parent = private_stat(database.parent, directory=True)
    maintenance, writer_path, _, _ = names(database)
    path = writer_path if writer else maintenance
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = private_stat(path)
        opened = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise LeaseError("identidade da lease mudou")
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive or writer else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LeaseError("banco ocupado; encerre o runtime cooperativamente") from exc
        if (database.parent.stat().st_dev, database.parent.stat().st_ino) != (parent.st_dev, parent.st_ino):
            raise LeaseError("diretório da lease mudou")
        sync_directory(database.parent)
        yield fd
    finally:
        os.close(fd)


def enrolled(database: Path) -> bool:
    marker = names(database)[2]
    if not marker.exists() and not marker.is_symlink():
        return False
    private_stat(marker)
    fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        payload = os.read(fd, 1025)
    finally:
        os.close(fd)
    if payload != origin_bytes(database):
        raise LeaseError("registro de origem das leases inválido")
    return True


def origin_bytes(database: Path) -> bytes:
    return json.dumps({"database": database.name, "protocol": 1}, sort_keys=True).encode()


def mark_birth(database: Path) -> None:
    """Call only under exclusive maintenance, after creating a NEW database."""
    marker = names(database)[2]
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        payload = origin_bytes(database)
        if os.write(fd, payload) != len(payload):
            raise LeaseError("registro de origem incompleto")
        os.fsync(fd)
    finally:
        os.close(fd)
    sync_directory(database.parent)


@contextmanager
def runtime_lease(database: Path):
    # Lock order is maintenance, then writer. Hold through worker drain.
    with lock(database), lock(database, writer=True):
        yield
