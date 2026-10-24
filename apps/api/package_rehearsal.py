"""Ensaio de instalação numa cópia sintética. Não assina e não abre o app.

Sem certificado, a assinatura fica bloqueada. O ensaio recusa a worktree,
o `uv` global e o banco diário. Não substitui o smoke da janela.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

PACKAGE_SMOKE = "BLOCKED"
SIGNATURE = "BLOCKED"
SUPPORTED_SCHEMA = "0025_prepared_effects"
COMPONENTS = (
    ("fastapi", "0.141.1", "MIT", "manter o aviso de licença"),
    ("uvicorn", "0.53.0", "BSD-3-Clause", "manter o aviso de licença"),
    ("pydantic", "2.13.5", "MIT", "manter o aviso de licença"),
    ("jsonschema", "4.23.0", "MIT", "manter o aviso de licença"),
    ("cryptography", "50.0.1", "Apache-2.0 OR BSD-3-Clause", "manter o aviso de licença"),
)


class PackageError(Exception):
    pass


def stage_install(root: Path, marker: str) -> dict[str, str]:
    _reject_forbidden(root)
    if root.exists():
        raise PackageError("instalação recusada")
    app = root / "app"
    data = root / "data"
    app.mkdir(parents=True)
    data.mkdir()
    (app / "serve.py").write_text("print('ensaio offline')\n", encoding="utf-8")
    (app / "marker.txt").write_text(marker, encoding="utf-8")
    database = data / "memory.sqlite3"
    _create_supported_database(database)
    manifest = {
        "executable": "app/serve.py",
        "database": "data/memory.sqlite3",
        "offline": "true",
        "capabilities": "captura,conversa,fixture",
        "marker": marker,
    }
    _write_manifest(app / "manifest.txt", manifest)
    return launch_spec(root)


def launch_spec(root: Path) -> dict[str, str]:
    _reject_forbidden(root)
    manifest = _read_manifest(root / "app" / "manifest.txt")
    executable = root / manifest["executable"]
    database = root / manifest["database"]
    if not executable.is_file() or not database.is_file():
        raise PackageError("instalação incompleta")
    if any(_forbidden(part) for part in (str(executable), str(database))):
        raise PackageError("instalação recusada")
    return {
        "executable": manifest["executable"],
        "database": manifest["database"],
        "offline": "true",
        "capabilities": manifest["capabilities"],
    }


def sign_payload(payload: bytes, certificate: bytes | None) -> dict[str, str]:
    if not certificate:
        return {"status": SIGNATURE, "signature": ""}
    raise PackageError("certificado real não é usado neste ensaio")


def apply_update(root: Path, marker: str, declared_hash: str, payload: bytes) -> None:
    if hashlib.sha256(payload).hexdigest() != declared_hash:
        raise PackageError("update adulterado")
    if sign_payload(payload, None)["status"] != SIGNATURE:
        raise PackageError("assinatura bloqueada")
    previous = root / "previous"
    if previous.exists():
        raise PackageError("update recusado")
    app = root / "app"
    shutil.copytree(app, previous)
    (app / "marker.txt").write_text(marker, encoding="utf-8")
    manifest = _read_manifest(app / "manifest.txt")
    manifest["marker"] = marker
    _write_manifest(app / "manifest.txt", manifest)


def rollback_app(root: Path) -> None:
    database = root / "data" / "memory.sqlite3"
    before = database.read_bytes()
    previous = root / "previous"
    if not previous.is_dir():
        raise PackageError("rollback recusado")
    app = root / "app"
    shutil.rmtree(app)
    shutil.move(str(previous), str(app))
    if database.read_bytes() != before:
        database.write_bytes(before)
        raise PackageError("rollback alterou o schema")


def schema_is_supported(database: Path) -> None:
    _reject_forbidden(database)
    before = database.read_bytes()
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise PackageError("schema recusado") from exc
    if versions != [SUPPORTED_SCHEMA] or before != database.read_bytes():
        raise PackageError("schema futuro recusado")


def license_report() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "component": name,
            "version": version,
            "license": license_name,
            "obligation": obligation,
            "advisory": "nao_consultado",
        }
        for name, version, license_name, obligation in COMPONENTS
    )


def diagnostic(root: Path) -> dict[str, str]:
    spec = launch_spec(root)
    return {
        "offline": spec["offline"],
        "database": spec["database"],
        "daily_database": "false",
        "smoke": PACKAGE_SMOKE,
        "signature": SIGNATURE,
    }


def export_session(database: Path, destination: Path) -> None:
    _reject_forbidden(database)
    _reject_forbidden(destination)
    if destination.exists():
        raise PackageError("exportação recusada")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id, body FROM local_captures WHERE owner = 'owner'"
        ).fetchall()
    except sqlite3.Error as exc:
        raise PackageError("exportação recusada") from exc
    finally:
        connection.close()
    lines = [f"{row[0]}\t{row[1]}" for row in rows]
    destination.write_text("\n".join(lines), encoding="utf-8")


def uninstall(root: Path, *, keep_data: bool) -> None:
    _reject_forbidden(root)
    data = root / "data"
    database = data / "memory.sqlite3"
    preserved = database.read_bytes() if keep_data and database.is_file() else b""
    shutil.rmtree(root)
    if keep_data:
        data.mkdir(parents=True)
        database.write_bytes(preserved)


def _create_supported_database(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE local_captures (id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
            (SUPPORTED_SCHEMA, "0" * 64, "2026-10-21T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()
    os_chmod(database)


def os_chmod(path: Path) -> None:
    path.chmod(0o600)


def _write_manifest(path: Path, manifest: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in sorted(manifest.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_manifest(path: Path) -> dict[str, str]:
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        found[key] = value
    return found


def _reject_forbidden(path: Path) -> None:
    if _forbidden(str(path.resolve())):
        raise PackageError("banco diário fora deste ensaio")


def _forbidden(value: str) -> bool:
    lowered = value.replace("\\", "/")
    daily = "/Library/Application Support/Jarvis"
    markers = (daily, "/.codex/worktrees/", "/uv/", "JARVIS_DATABASE_PATH")
    return any(marker in lowered for marker in markers)
