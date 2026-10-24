"""Ensaio de instalação. Não assina, não abre o app e não usa o banco diário."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from package_rehearsal import (
    PACKAGE_SMOKE,
    SIGNATURE,
    PackageError,
    apply_update,
    diagnostic,
    export_session,
    launch_spec,
    license_report,
    rollback_app,
    schema_is_supported,
    sign_payload,
    stage_install,
    uninstall,
)


def test_clean_install_does_not_point_at_the_worktree_or_the_daily_database(tmp_path):
    spec = stage_install(tmp_path / "install", "primeira")
    assert spec["executable"] == "app/serve.py"
    assert spec["database"] == "data/memory.sqlite3"
    assert spec["offline"] == "true"
    assert "worktrees" not in spec["executable"]
    assert "Application Support" not in spec["database"]
    report = diagnostic(tmp_path / "install")
    assert report["daily_database"] == "false"
    assert report["smoke"] == "BLOCKED"
    assert report["signature"] == "BLOCKED"
    with pytest.raises(PackageError, match="banco diário"):
        stage_install(Path.home() / "Library" / "Application Support" / "Jarvis" / "ensaio", "nao")


def test_signature_stays_blocked_and_a_tampered_update_is_refused(tmp_path):
    root = tmp_path / "install"
    stage_install(root, "primeira")
    payload = b"pacote-sintetico"
    signed = sign_payload(payload, None)
    assert signed == {"status": SIGNATURE, "signature": ""}
    with pytest.raises(PackageError, match="certificado real"):
        sign_payload(payload, b"certificado-falso")
    before = (root / "app" / "marker.txt").read_text(encoding="utf-8")
    with pytest.raises(PackageError, match="update adulterado"):
        apply_update(root, "segunda", "0" * 64, payload)
    assert (root / "app" / "marker.txt").read_text(encoding="utf-8") == before
    apply_update(root, "segunda", hashlib.sha256(payload).hexdigest(), payload)
    assert launch_spec(root)["capabilities"] == "captura,conversa,fixture"
    assert (root / "data" / "memory.sqlite3").is_file()


def test_future_schema_is_refused_and_rollback_keeps_the_database(tmp_path):
    root = tmp_path / "install"
    stage_install(root, "primeira")
    database = root / "data" / "memory.sqlite3"
    before = database.read_bytes()
    payload = b"pacote-sintetico"
    apply_update(root, "segunda", hashlib.sha256(payload).hexdigest(), payload)
    rollback_app(root)
    assert (root / "app" / "marker.txt").read_text(encoding="utf-8") == "primeira"
    assert database.read_bytes() == before
    schema_is_supported(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES ('9999_future', ?, ?)",
            ("f" * 64, "2026-10-21T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()
    future = database.read_bytes()
    with pytest.raises(PackageError, match="schema futuro recusado"):
        schema_is_supported(database)
    assert database.read_bytes() == future


def test_export_and_uninstall_can_keep_or_remove_only_the_rehearsal_data(tmp_path):
    root = tmp_path / "install"
    stage_install(root, "primeira")
    database = root / "data" / "memory.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO local_captures(id, owner, body) VALUES ('ab', 'owner', 'nota sintetica')"
        )
        connection.commit()
    finally:
        connection.close()
    exported = tmp_path / "exportacao.txt"
    export_session(database, exported)
    assert exported.read_text(encoding="utf-8") == "ab\tnota sintetica"
    uninstall(root, keep_data=True)
    assert not (root / "app").exists()
    assert database.is_file()
    uninstall(root, keep_data=False)
    assert not root.exists()
    licenses = license_report()
    assert {item["component"] for item in licenses} == {
        "fastapi", "uvicorn", "pydantic", "jsonschema", "cryptography",
    }
    assert all(item["advisory"] == "nao_consultado" for item in licenses)
    assert PACKAGE_SMOKE == "BLOCKED"
