"""Adversarial checks against the approved DEC-08-A contract. Synthetic paths only."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

import database_leases as leases
import restore_activation as activation
from backup_recovery import create_backup
from memory_store import SQLiteMemoryStore
from sealed_database import PlaintextDatabaseRefused
from test_restore_activation import PASSWORD, make_legacy_store, make_sealed_store, marker


def test_copied_database_without_origin_stays_ineligible(tmp_path, encrypted_store_factory):
    born = make_legacy_store(tmp_path, "born", 11)
    copied = tmp_path / "copied" / "memory.sqlite3"
    copied.parent.mkdir(mode=0o700)
    copied.write_bytes(born.path.read_bytes())
    copied.chmod(0o600)
    reopened = encrypted_store_factory(copied)
    with pytest.raises(PlaintextDatabaseRefused):
        reopened.initialize()
    assert not leases.names(copied)[2].exists()
    assert not leases.enrolled(copied)
    source = make_sealed_store(tmp_path, "source", 22, encrypted_store_factory)
    archive = create_backup(
        source.path, tmp_path / "backups", PASSWORD,
        storage_key=encrypted_store_factory.storage_key,
    )
    with pytest.raises(activation.ActivationError, match="preexistente"):
        activation.prepare_activation(archive, copied, PASSWORD, confirm_legacy_resurrection=True)
    assert not leases.names(copied)[2].exists()
    assert marker(copied) == 11


def test_symlink_spelling_and_dotdot_are_refused_canonical_path_is_not(pair_paths):
    active, archive = pair_paths
    canonical = active.path
    dotted = canonical.parent / ".." / canonical.parent.name / canonical.name
    with pytest.raises(leases.LeaseError, match="inválido"):
        leases.checked_path(dotted)
    link = canonical.parent / "linked.sqlite3"
    link.symlink_to(canonical)
    with pytest.raises(leases.LeaseError, match="simbólico"):
        activation.prepare_activation(archive, link, PASSWORD, confirm_legacy_resurrection=True)
    if canonical.is_relative_to("/private/var") and Path("/var").is_symlink():
        alias = Path("/var") / canonical.relative_to("/private/var")
        with pytest.raises(leases.LeaseError, match="simbólico"):
            activation.prepare_activation(archive, alias, PASSWORD, confirm_legacy_resurrection=True)
    plan = activation.prepare_activation(archive, canonical, PASSWORD, confirm_legacy_resurrection=True)
    assert plan.database == canonical


def test_incompatible_schema_record_blocks_recovery_and_keeps_bytes(tmp_path):
    active = make_legacy_store(tmp_path, "active", 11)
    before = active.path.read_bytes()
    root = leases.names(active.path)[3]
    root.mkdir(mode=0o700)
    record = {
        "version": 1,
        "operation": "ab" * 16,
        "state": "COMMITTED",
        "old": "a" * 64,
        "new": "b" * 64,
        "schema": "c" * 64,
    }
    state = root / "state.json"
    state.write_bytes(activation._json(record))
    state.chmod(0o600)
    with pytest.raises(activation.ActivationError, match="incompat"):
        activation.recover_activation(active.path)
    with pytest.raises(activation.ActivationError, match="incompat"):
        activation.recover_activation(active.path)
    assert active.path.read_bytes() == before
    assert marker(active.path) == 11


def test_successful_activation_consolidates_wal_and_keeps_independent_rollback(tmp_path, encrypted_store_factory):
    import os
    import subprocess
    import sys
    active = make_legacy_store(tmp_path, "active", 11)
    script = """
import os, sqlite3, sys
from memory_store import SQLiteMemoryStore
connection = sqlite3.connect(sys.argv[1], isolation_level=None)
connection.execute('PRAGMA journal_mode=WAL')
connection.execute('PRAGMA wal_autocheckpoint=0')
SQLiteMemoryStore._insert_audit(connection, 'memory_read', 33)
os._exit(75)
"""
    completed = subprocess.run([sys.executable, "-c", script, str(active.path)], cwd=Path(__file__).parent, timeout=30)
    assert completed.returncode == 75
    assert Path(str(active.path) + "-wal").stat().st_size > 0
    source = make_sealed_store(tmp_path, "source", 22, encrypted_store_factory)
    archive = create_backup(
        source.path, tmp_path / "backups", PASSWORD,
        storage_key=encrypted_store_factory.storage_key,
    )
    plan = activation.prepare_activation(archive, active.path, PASSWORD, confirm_legacy_resurrection=True)
    rollback = activation.activate(plan, plan.confirmation)
    assert marker(active.path) == 22
    assert marker(rollback) == 11
    with closing(sqlite3.connect(rollback)) as connection:
        assert connection.execute(
            "SELECT record_count FROM audit_entries ORDER BY rowid"
        ).fetchall() == [(11,), (33,)]
    assert rollback.stat().st_ino != active.path.stat().st_ino
    assert not any(Path(str(active.path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    activation.recover_activation(active.path)
    assert marker(active.path) == 22
    assert activation._state(active.path)["state"] == "COMMITTED"


def test_initialize_recovery_respects_cooperative_writer_lease(tmp_path, encrypted_store_factory):
    active = make_legacy_store(tmp_path, "active", 11)
    source = make_sealed_store(tmp_path, "source", 22, encrypted_store_factory)
    archive = create_backup(
        source.path, tmp_path / "backups", PASSWORD,
        storage_key=encrypted_store_factory.storage_key,
    )
    script = """
import os, sys
from pathlib import Path
import restore_activation as activation
def crash(name):
    if name == "switch:after":
        os._exit(73)
plan = activation.prepare_activation(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], confirm_legacy_resurrection=True)
activation._point = crash
activation.activate(plan, plan.confirmation)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(archive), str(active.path), PASSWORD],
        cwd=Path(__file__).parent,
        timeout=30,
    )
    assert completed.returncode == 73
    assert activation._state(active.path)["state"] == "PREPARED"
    assert marker(active.path) == 22
    with leases.lock(active.path, writer=True):
        with pytest.raises(leases.LeaseError, match="ocupado"):
            encrypted_store_factory(active.path).initialize()
    assert activation._state(active.path)["state"] == "PREPARED"
    assert marker(active.path) == 22
    with pytest.raises(PlaintextDatabaseRefused):
        encrypted_store_factory(active.path).initialize()
    assert activation._state(active.path)["state"] == "ROLLED_BACK"
    assert marker(active.path) == 11


@pytest.fixture
def pair_paths(tmp_path, encrypted_store_factory):
    active = make_legacy_store(tmp_path, "active", 11)
    source = make_sealed_store(tmp_path, "source", 22, encrypted_store_factory)
    archive = create_backup(
        source.path, tmp_path / "backups", PASSWORD,
        storage_key=encrypted_store_factory.storage_key,
    )
    return active, archive
