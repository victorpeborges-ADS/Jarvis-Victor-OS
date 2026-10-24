"""Activation tests use explicit synthetic roots, never default database paths."""
from __future__ import annotations

import errno
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import backup_cli
import backup_recovery as backup
import database_leases as leases
import memory_store
import restore_activation as activation
from local_automations import create_automation
from memory_store import SQLiteMemoryStore
from sealed_database import MAGIC, PlaintextDatabaseRefused

PASSWORD = "synthetic-activation-password-only"
API = Path(__file__).parent


@pytest.fixture(autouse=True)
def no_default_database(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("activation test attempted to resolve default database")
    monkeypatch.setattr(memory_store, "default_database_path", forbidden)
    monkeypatch.setattr(backup_cli, "default_database_path", forbidden)


class _LeaseBoundConnection(sqlite3.Connection):
    lease = None

    def close(self):
        try:
            super().close()
        finally:
            if self.lease is not None:
                lease, self.lease = self.lease, None
                lease.__exit__(None, None, None)


class LegacySQLiteStore:
    """Explicit clear-SQLite fixture for the legacy activation contract."""

    def __init__(self, path: Path):
        self.path = path
        self._identity = None
        self.initialize()

    def initialize(self):
        if not self.path.exists():
            if leases.enrolled(self.path):
                raise memory_store.MemoryStoreError("banco registrado ausente; manutenção necessária")
            raise memory_store.MemoryStoreError("banco legado ausente")
        info = self.path.stat()
        self._identity = (info.st_dev, info.st_ino)

    def _connect(self):
        if not self.path.exists():
            self.initialize()
        info = self.path.stat()
        if self._identity != (info.st_dev, info.st_ino):
            raise memory_store.MemoryStoreError("geração do banco mudou; reinicie o store")
        lease = leases.lock(self.path)
        lease.__enter__()
        connection = None
        try:
            connection = sqlite3.connect(
                self.path, timeout=0, isolation_level=None, factory=_LeaseBoundConnection
            )
            connection.lease = lease
            connection.row_factory = sqlite3.Row
            activation.assert_ready(self.path)
            return connection
        except BaseException:
            if connection is not None:
                connection.close()
            else:
                lease.__exit__(None, None, None)
            raise

    @contextmanager
    def transaction(self):
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_audit(self, operation, record_count=0):
        with self.transaction() as connection:
            SQLiteMemoryStore._insert_audit(connection, operation, record_count)

    @contextmanager
    def runtime(self):
        with leases.lock(self.path), leases.lock(self.path, writer=True):
            yield


def make_legacy_store(root, name, marker):
    path = root / name / "memory.sqlite3"
    assert path.is_relative_to(root) and not path.is_relative_to(memory_store.REPOSITORY_ROOT)
    path.parent.mkdir(mode=0o700)
    bootstrap = SQLiteMemoryStore(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        bootstrap._apply_migrations(connection)
        bootstrap._validate_schema(connection)
        SQLiteMemoryStore._insert_audit(connection, "memory_read", marker)
        connection.commit()
    os.chmod(path, 0o600)
    with leases.lock(path, exclusive=True), leases.lock(path, writer=True):
        leases.mark_birth(path)
    return LegacySQLiteStore(path)


def make_sealed_store(root, name, marker, encrypted_store_factory):
    path = root / name / "memory.sqlite3"
    assert path.is_relative_to(root) and not path.is_relative_to(memory_store.REPOSITORY_ROOT)
    store = encrypted_store_factory(path)
    store.initialize()
    store.record_audit("memory_read", marker)
    return store


@pytest.fixture
def pair(tmp_path, encrypted_store_factory):
    active = make_legacy_store(tmp_path, "active", 11)
    source = make_sealed_store(tmp_path, "source", 22, encrypted_store_factory)
    archive = backup.create_backup(
        source.path, tmp_path / "backups", PASSWORD,
        storage_key=encrypted_store_factory.storage_key,
    )
    return active, source, archive


def marker(path):
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        return connection.execute("SELECT record_count FROM audit_entries WHERE operation='memory_read' ORDER BY rowid LIMIT 1").fetchone()[0]


def plan_for(pair):
    active, _, archive = pair
    return activation.prepare_activation(archive, active.path, PASSWORD, confirm_legacy_resurrection=True)


def test_success_retains_independent_rollback_and_invalidates_old_store(pair):
    active, source, archive = pair
    original_archive = archive.read_bytes()
    plan = plan_for(pair)
    rollback = activation.activate(plan, plan.confirmation)
    assert marker(active.path) == 22
    assert marker(rollback) == 11
    assert archive.read_bytes() == original_archive
    assert rollback.stat().st_ino != active.path.stat().st_ino
    assert rollback.stat().st_nlink == active.path.stat().st_nlink == 1
    assert activation._state(active.path)["state"] == "COMMITTED"
    with pytest.raises(memory_store.MemoryStoreError, match="geração"):
        active.record_audit("memory_read", 33)
    reopened = LegacySQLiteStore(active.path)
    reopened.record_audit("memory_read", 44)
    activation.recover_activation(active.path)
    assert marker(active.path) == 22
    assert marker(rollback) == 11
    assert not any(Path(str(active.path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def test_automations_are_paused_and_runs_not_replayed(tmp_path, encrypted_store_factory):
    active = make_legacy_store(tmp_path, "active", 11)
    source = make_sealed_store(tmp_path, "source", 22, encrypted_store_factory)
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    automation = create_automation(source, owner="owner", kind="reminder", title="Sintético",
                                   recurrence="daily", local_schedule="09:00", timezone_name="UTC",
                                   message="Sintético", now=now)
    with source.transaction() as connection:
        for index, status in enumerate(("pending", "running", "retry_wait", "deferred", "succeeded")):
            connection.execute("""INSERT INTO local_automation_runs
                (id,automation_id,scheduled_for_utc,idempotency_key,workflow_version,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""", (f"{index:032x}", automation["id"], f"2026-10-{17+index}T09:00:00+00:00",
                                             f"synthetic-{index}", automation["workflow_version"], status, now.isoformat(), now.isoformat()))
    archive = backup.create_backup(
        source.path, tmp_path / "backups", PASSWORD,
        storage_key=encrypted_store_factory.storage_key,
    )
    plan = activation.prepare_activation(archive, active.path, PASSWORD, confirm_legacy_resurrection=True)
    activation.activate(plan, plan.confirmation)
    with closing(sqlite3.connect(active.path)) as connection:
        assert connection.execute("SELECT state,next_run_at_utc FROM local_automations").fetchall() == [("paused", None)]
        assert connection.execute("SELECT status FROM local_automation_runs ORDER BY id").fetchall() == [("superseded",)] * 4 + [("succeeded",)]


@pytest.mark.parametrize("damage", ["old", "future", "checksum", "structure", "corrupt", "password"])
def test_rejects_backup_before_touching_active(pair, tmp_path, damage):
    active, source, archive = pair
    if damage in {"old", "future", "checksum", "structure"}:
        with source.transaction() as connection:
            if damage == "old":
                connection.execute("DELETE FROM schema_migrations WHERE version=(SELECT MAX(version) FROM schema_migrations)")
            elif damage == "future":
                connection.execute("INSERT INTO schema_migrations(version,checksum,applied_at) VALUES ('9999_future',?,?)", ("f" * 64, "synthetic"))
            elif damage == "checksum":
                connection.execute("UPDATE schema_migrations SET checksum=?", ("f" * 64,))
            else:
                connection.execute("CREATE TABLE unexpected_schema (id TEXT)")
        with closing(source._connect()) as connection, closing(sqlite3.connect(":memory:")) as snapshot:
            connection.backup(snapshot)
            image = snapshot.serialize()
        archive.write_bytes(backup._seal_snapshot(image, PASSWORD))
    elif damage == "corrupt":
        archive.write_bytes(backup._seal_snapshot(b"not a SQLite database", PASSWORD))
    before = active.path.read_bytes()
    with pytest.raises(backup.BackupError):
        activation.prepare_activation(archive, active.path, "incorrect synthetic password" if damage == "password" else PASSWORD, confirm_legacy_resurrection=True)
    assert active.path.read_bytes() == before
    assert marker(active.path) == 11
    assert not leases.names(active.path)[3].exists()


def test_sealed_activation_target_is_refused_without_staging(pair, tmp_path, encrypted_store_factory):
    _, _, archive = pair
    sealed = make_sealed_store(tmp_path, "sealed-target", 33, encrypted_store_factory)
    before = sealed.path.read_bytes()
    with pytest.raises(activation.ActivationError, match="snapshot selado"):
        activation.prepare_activation(archive, sealed.path, PASSWORD, confirm_legacy_resurrection=True)
    assert sealed.path.read_bytes() == before
    assert not leases.names(sealed.path)[3].exists()


def test_existing_database_cannot_be_admitted_implicitly(pair):
    active, _, archive = pair
    leases.names(active.path)[2].unlink()  # simulate a pre-protocol database
    active.initialize()  # explicit legacy fixture never adds origin
    assert not leases.enrolled(active.path)
    with pytest.raises(activation.ActivationError, match="preexistente"):
        activation.prepare_activation(archive, active.path, PASSWORD, confirm_legacy_resurrection=True)


def test_missing_registered_database_never_becomes_empty(pair):
    active, _, _ = pair
    active.path.unlink()
    with pytest.raises(memory_store.MemoryStoreError, match="ausente"):
        active.initialize()
    assert not active.path.exists()


def test_confirmation_binds_target_image_and_current_state(pair):
    active, _, _ = pair
    plan = plan_for(pair)
    with pytest.raises(activation.ActivationError, match="confirmação"):
        activation.activate(plan, "ATIVAR")
    active.record_audit("memory_read", 33)
    with pytest.raises(activation.ActivationError, match="mudou"):
        activation.activate(plan, plan.confirmation)
    assert marker(active.path) == 11


def test_cli_requires_interactive_confirmation_and_explicit_target(pair, monkeypatch, capsys):
    active, _, archive = pair
    monkeypatch.setattr(backup_cli, "_prompt_passphrase", lambda **kwargs: PASSWORD)
    monkeypatch.setattr("builtins.input", lambda prompt: "não")
    assert backup_cli.run(["activate", str(archive), "--database", str(active.path), "--confirm-legacy-resurrection"]) == 2
    assert marker(active.path) == 11
    assert "Destino a substituir" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt: plan_for(pair).confirmation)
    assert backup_cli.run(["activate", str(archive), "--database", str(active.path), "--confirm-legacy-resurrection"]) == 0
    assert marker(active.path) == 22


def test_cli_refuses_non_tty_activation(pair, monkeypatch):
    active, _, archive = pair
    monkeypatch.setattr(backup_cli.sys.stdin, "isatty", lambda: False)
    assert backup_cli.run(["activate", str(archive), "--database", str(active.path), "--confirm-legacy-resurrection"]) == 2
    assert marker(active.path) == 11


@pytest.mark.parametrize("held", ["runtime", "reader", "transaction", "backup", "writer", "activation"])
def test_concurrent_holders_prevent_activation(pair, held):
    active, _, _ = pair
    plan = plan_for(pair)
    contexts = {
        "runtime": active.runtime,
        "reader": lambda: closing(active._connect()),
        "transaction": active.transaction,
        "backup": lambda: leases.lock(active.path),
        "writer": lambda: leases.lock(active.path, writer=True),
        "activation": lambda: leases.lock(active.path, exclusive=True),
    }
    with contexts[held]():
        with pytest.raises(leases.LeaseError):
            activation.activate(plan, plan.confirmation)
    assert marker(active.path) == 11


def test_maintenance_blocks_all_new_connections_backup_and_runtime(pair, encrypted_store_factory):
    active, _, archive = pair
    with leases.lock(active.path, exclusive=True):
        with pytest.raises(leases.LeaseError):
            active.record_audit("memory_read", 33)
        with pytest.raises(backup.BackupError):
            backup.create_backup(
                active.path, archive.parent, PASSWORD,
                storage_key=encrypted_store_factory.storage_key,
            )
        with pytest.raises(leases.LeaseError):
            with active.runtime():
                pytest.fail("runtime crossed maintenance")
    assert marker(active.path) == 11


def test_runtime_lease_is_held_between_connections_in_separate_process(pair):
    active, _, _ = pair
    script = """
import sys
from pathlib import Path
import database_leases
with database_leases.runtime_lease(Path(sys.argv[1])):
 print('ready', flush=True)
 sys.stdin.readline()
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(active.path)], cwd=API,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(leases.LeaseError):
            plan_for(pair)
        child.communicate("done\n", timeout=15)
        assert child.returncode == 0
    finally:
        # This test creates the child; never signal user/app processes.
        if child.poll() is None:
            child.communicate("done\n", timeout=15)
    assert plan_for(pair)


def test_space_preflight_and_enospc_do_not_replace_active(pair, monkeypatch):
    active, _, _ = pair
    plan = plan_for(pair)
    monkeypatch.setattr(activation.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(activation.ActivationError, match="espaço"):
        activation.activate(plan, plan.confirmation)
    assert marker(active.path) == 11


@pytest.mark.parametrize("kind", ["database_symlink", "parent_symlink", "database_hardlink", "sidecar_symlink", "sidecar_hardlink", "lock_symlink", "marker_corrupt", "record_missing", "record_malformed", "permissions"])
def test_unsafe_paths_and_evidence_fail_closed(pair, tmp_path, kind):
    active, _, archive = pair
    target = active.path
    if kind == "database_symlink":
        target = active.path.parent / "linked.sqlite3"
        target.symlink_to(active.path)
    elif kind == "parent_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(active.path.parent, target_is_directory=True)
        target = alias / active.path.name
    elif kind == "database_hardlink":
        os.link(active.path, active.path.parent / "alias.sqlite3")
    elif kind.startswith("sidecar_"):
        sidecar = Path(str(active.path) + "-wal")
        if kind.endswith("symlink"):
            sidecar.symlink_to(archive)
        else:
            os.link(archive, sidecar)
    elif kind == "lock_symlink":
        lock = leases.names(active.path)[0]
        lock.unlink()
        lock.symlink_to(archive)
    elif kind == "marker_corrupt":
        leases.names(active.path)[2].write_bytes(b"{}")
    elif kind.startswith("record_"):
        root = leases.names(active.path)[3]
        root.mkdir(mode=0o700)
        if kind.endswith("malformed"):
            (root / "state.json").write_bytes(b"{}")
            (root / "state.json").chmod(0o600)
    else:
        active.path.chmod(0o644)
    with pytest.raises((backup.BackupError, leases.LeaseError, OSError)):
        activation.prepare_activation(archive, target, PASSWORD, confirm_legacy_resurrection=True)


# Every I/O boundary exposed by the activation protocol, including the interval
# where replacement succeeded but PREPARED is still the durable authority.
WRITE_LABELS = ["record-BUILDING", "rollback", "rollback-ready", "candidate", "record-PREPARED", "record-SWITCHED", "record-COMMITTED"]
FAULTS = [f"{label}:{edge}" for label in WRITE_LABELS for edge in ("before_write", "after_write", "after_fsync", "after_dirsync")]
FAULTS += [f"{state}:{edge}" for state in ("BUILDING", "PREPARED", "SWITCHED", "COMMITTED") for edge in ("before_publish", "after_publish", "durable")]
FAULTS += ["area:durable", "checkpoint:before", "checkpoint:after", "suspend:before", "suspend:after", "switch:before", "switch:after", "switch:durable", "validation:after"]
FAULTS += ["suspend:begin", "suspend:paused", "suspend:runs", "suspend:committed"]


@pytest.mark.parametrize("point", FAULTS)
def test_crash_at_every_activation_boundary_recovers_idempotently(pair, point):
    active, _, archive = pair
    script = """
import os,sys
from pathlib import Path
import restore_activation as a
def crash(name):
 if name == sys.argv[3]: os._exit(73)
plan=a.prepare_activation(Path(sys.argv[1]),Path(sys.argv[2]),'synthetic-activation-password-only', confirm_legacy_resurrection=True)
a._point=crash
a.activate(plan,plan.confirmation)
"""
    result = subprocess.run([sys.executable, "-c", script, str(archive), str(active.path), point],
                            cwd=API, capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stderr
    state_file = leases.names(active.path)[3] / "state.json"
    if not state_file.exists():
        # Crash before the first durable record: ambiguous intent is blocked.
        with pytest.raises((OSError, backup.BackupError)):
            activation.recover_activation(active.path)
        assert marker(active.path) == 11
        return
    state = activation._state(active.path)["state"]
    expected = 22 if state == "COMMITTED" else 11
    activation.recover_activation(active.path)
    activation.recover_activation(active.path)
    assert marker(active.path) == expected
    assert archive.exists()
    for rollback in leases.names(active.path)[3].glob("*/rollback.sqlite3"):
        # Incomplete pre-PREPARED writes are not accepted as valid rollbacks.
        if rollback.stat().st_size:
            assert marker(rollback) == 11


@pytest.mark.parametrize("point", ["candidate:after_write", "rollback:after_fsync", "PREPARED:durable", "switch:after", "SWITCHED:after_publish", "COMMITTED:before_publish"])
@pytest.mark.parametrize("error", [errno.ENOSPC, errno.EIO, errno.EXDEV, errno.EACCES])
def test_io_failure_preserves_evidence_and_recovers(pair, point, error, monkeypatch):
    active, _, _ = pair
    plan = plan_for(pair)
    def fail(name):
        if name == point:
            raise OSError(error, "synthetic failure")
    monkeypatch.setattr(activation, "_point", fail)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    monkeypatch.setattr(activation, "_point", lambda name: None)
    activation.recover_activation(active.path)
    assert marker(active.path) == 11


@pytest.mark.parametrize("point", ["rollback:before", "rollback:after", "rollback:durable", "ROLLED_BACK:before_publish", "ROLLED_BACK:after_publish"])
def test_recovery_itself_can_crash_and_retry(pair, point, monkeypatch):
    active, _, _ = pair
    plan = plan_for(pair)
    def fail(name):
        if name == "switch:after":
            raise OSError(errno.EIO, "synthetic")
    monkeypatch.setattr(activation, "_point", fail)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    script = """
import os,sys
import restore_activation as a
def crash(name):
 if name == sys.argv[2]: os._exit(74)
a._point=crash
a.recover_activation(sys.argv[1])
"""
    result = subprocess.run([sys.executable, "-c", script, str(active.path), point], cwd=API, timeout=30)
    assert result.returncode == 74
    monkeypatch.setattr(activation, "_point", lambda name: None)
    activation.recover_activation(active.path)
    activation.recover_activation(active.path)
    assert marker(active.path) == 11


def test_startup_recovers_before_migrations_and_blocks_unknown_hash(pair, monkeypatch, encrypted_store_factory):
    active, _, _ = pair
    plan = plan_for(pair)
    def fail(name):
        if name == "switch:after":
            raise OSError(errno.EIO, "synthetic")
    monkeypatch.setattr(activation, "_point", fail)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    with closing(sqlite3.connect(active.path)) as connection:
        SQLiteMemoryStore._insert_audit(connection, "memory_read", 99)
        connection.commit()
    monkeypatch.setattr(activation, "_point", lambda name: None)
    called = []
    monkeypatch.setattr(SQLiteMemoryStore, "_apply_migrations", lambda *args: called.append(True))
    with pytest.raises(backup.BackupError, match="inesperado"):
        encrypted_store_factory(active.path).initialize()
    assert not called


def test_raw_sqlite_reader_blocks_checkpoint_and_preserves_wal(pair):
    active, _, _ = pair
    # Simulate a non-cooperative SQLite reader. Protocol holders are rejected
    # earlier; SQLite busy must also fail closed, without deleting WAL.
    with closing(sqlite3.connect(active.path, isolation_level=None)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        with closing(sqlite3.connect(active.path, isolation_level=None)) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM audit_entries").fetchall()
            SQLiteMemoryStore._insert_audit(writer, "memory_read", 33)
            plan = plan_for(pair)
            wal = Path(str(active.path) + "-wal")
            assert wal.exists() and wal.stat().st_size > 0
            with pytest.raises(backup.BackupError):
                activation.activate(plan, plan.confirmation)
            assert wal.exists() and wal.stat().st_size > 0
            reader.execute("ROLLBACK")
    activation.recover_activation(active.path)
    with closing(sqlite3.connect(active.path)) as connection:
        assert connection.execute("SELECT record_count FROM audit_entries ORDER BY rowid").fetchall() == [(11,), (33,)]


@pytest.mark.parametrize("damage", ["active_missing", "rollback_corrupt", "ready_corrupt", "record_duplicate", "record_unknown_state"])
def test_ambiguous_precommit_evidence_blocks_startup(pair, monkeypatch, damage, encrypted_store_factory):
    active, _, _ = pair
    plan = plan_for(pair)
    def fail(name):
        if name == "switch:after":
            raise OSError(errno.EIO, "synthetic")
    monkeypatch.setattr(activation, "_point", fail)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    record = activation._state(active.path)
    area = leases.names(active.path)[3] / record["operation"]
    if damage == "active_missing":
        active.path.unlink()
    elif damage.endswith("corrupt"):
        name = "rollback.sqlite3" if damage == "rollback_corrupt" else "rollback-ready.sqlite3"
        (area / name).write_bytes(b"corrupt synthetic image")
    else:
        state = leases.names(active.path)[3] / "state.json"
        payload = state.read_bytes()
        state.write_bytes(payload[:-1] + b',"version":1}' if damage == "record_duplicate" else payload.replace(b'PREPARED', b'UNKNOWN!'))
    called = []
    monkeypatch.setattr(SQLiteMemoryStore, "_apply_migrations", lambda *args: called.append(True))
    monkeypatch.setattr(activation, "_point", lambda name: None)
    with pytest.raises((OSError, backup.BackupError, leases.LeaseError)):
        encrypted_store_factory(active.path).initialize()
    assert not called
    assert (area / "rollback.sqlite3").exists()


def test_committed_corruption_never_triggers_automatic_rollback(pair, encrypted_store_factory):
    active, _, _ = pair
    plan = plan_for(pair)
    rollback = activation.activate(plan, plan.confirmation)
    active.path.write_bytes(b"synthetic corruption after commit")
    with pytest.raises(backup.BackupError):
        encrypted_store_factory(active.path).initialize()
    assert active.path.read_bytes() == b"synthetic corruption after commit"
    assert marker(rollback) == 11


def test_startup_completes_precommit_rollback_before_any_migration(pair, monkeypatch, encrypted_store_factory):
    active, _, _ = pair
    plan = plan_for(pair)
    def fail(name):
        if name == "switch:after":
            raise OSError(errno.EIO, "synthetic")
    monkeypatch.setattr(activation, "_point", fail)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    monkeypatch.setattr(activation, "_point", lambda name: None)
    called = []
    monkeypatch.setattr(SQLiteMemoryStore, "_apply_migrations", lambda *args: called.append(True))
    with pytest.raises(PlaintextDatabaseRefused):
        encrypted_store_factory(active.path).initialize()
    assert activation._state(active.path)["state"] == "ROLLED_BACK"
    assert marker(active.path) == 11
    assert not called


@pytest.mark.parametrize("operation", ["partial_write", "fsync", "replace"])
def test_real_io_primitives_fail_without_losing_active(pair, monkeypatch, operation):
    active, _, _ = pair
    plan = plan_for(pair)
    real_write, real_fsync, real_replace = os.write, os.fsync, os.replace
    armed = False
    def arm(name):
        nonlocal armed
        wanted = "switch:before" if operation == "replace" else "candidate:before_write"
        if name == wanted:
            armed = True
    monkeypatch.setattr(activation, "_point", arm)
    def write(fd, payload):
        if armed:
            real_write(fd, payload[:max(1, len(payload) // 2)])
            raise OSError(errno.ENOSPC, "synthetic partial write")
        return real_write(fd, payload)
    def fsync(fd):
        if armed:
            raise OSError(errno.EIO, "synthetic fsync failure")
        return real_fsync(fd)
    def replace(source, destination):
        if armed:
            raise OSError(errno.EXDEV, "synthetic rename failure")
        return real_replace(source, destination)
    monkeypatch.setattr(os, {"partial_write": "write", "fsync": "fsync", "replace": "replace"}[operation],
                        {"partial_write": write, "fsync": fsync, "replace": replace}[operation])
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    assert marker(active.path) == 11
    armed = False
    activation.recover_activation(active.path)
    assert marker(active.path) == 11


def test_lock_inodes_remain_stable_across_activation(pair):
    active, _, _ = pair
    plan = plan_for(pair)
    lock_paths = leases.names(active.path)[:2]
    before = [(p.stat().st_dev, p.stat().st_ino) for p in lock_paths]
    activation.activate(plan, plan.confirmation)
    assert before == [(p.stat().st_dev, p.stat().st_ino) for p in lock_paths]


def test_captures_and_workflow_rows_survive_without_replaying_tools(pair, encrypted_store_factory):
    from local_captures import create_capture, list_captures
    from workflow_executor import WorkflowExecutor
    active, source, archive = pair
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    capture = create_capture(source, "owner", "Captura inteiramente sintética", now)
    task = WorkflowExecutor(source).submit("owner", {"tool_id": "draft_note", "arguments": {"title": "Sintético", "body": "Apenas teste"}}, "synthetic-restore-workflow", now)
    with closing(source._connect()) as connection:
        connection.row_factory = None
        expected = connection.execute("SELECT * FROM workflow_tasks").fetchall()
    archive = backup.create_backup(
        source.path, archive.parent, PASSWORD,
        storage_key=encrypted_store_factory.storage_key,
    )
    plan = activation.prepare_activation(archive, active.path, PASSWORD, confirm_legacy_resurrection=True)
    activation.activate(plan, plan.confirmation)
    with closing(sqlite3.connect(active.path)) as connection:
        assert connection.execute(
            "SELECT id FROM local_captures WHERE owner='owner'"
        ).fetchone()[0] == capture["id"]
        assert connection.execute("SELECT * FROM workflow_tasks").fetchall() == expected
        assert connection.execute("SELECT COUNT(*) FROM workflow_executions").fetchone()[0] == 0


def test_committed_wal_is_included_in_independent_rollback(pair):
    active, _, _ = pair
    script = """
import os,sqlite3,sys
from memory_store import SQLiteMemoryStore
c=sqlite3.connect(sys.argv[1],isolation_level=None)
c.execute('PRAGMA journal_mode=WAL')
c.execute('PRAGMA wal_autocheckpoint=0')
SQLiteMemoryStore._insert_audit(c,'memory_read',33)
os._exit(75)
"""
    assert subprocess.run([sys.executable, "-c", script, str(active.path)], cwd=API, timeout=30).returncode == 75
    assert Path(str(active.path) + "-wal").stat().st_size > 0
    plan = plan_for(pair)
    rollback = activation.activate(plan, plan.confirmation)
    with closing(sqlite3.connect(rollback)) as connection:
        assert connection.execute("SELECT record_count FROM audit_entries ORDER BY rowid").fetchall() == [(11,), (33,)]
    assert marker(active.path) == 22


def test_hot_journal_is_recovered_by_sqlite_before_aborting_building(pair, monkeypatch):
    active, _, _ = pair
    plan = plan_for(pair)
    def fail(name):
        if name == "checkpoint:before":
            raise OSError(errno.EIO, "synthetic")
    monkeypatch.setattr(activation, "_point", fail)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    script = """
import os,sqlite3,sys
from memory_store import SQLiteMemoryStore
c=sqlite3.connect(sys.argv[1],isolation_level=None)
c.execute('PRAGMA journal_mode=DELETE')
c.execute('PRAGMA cache_size=2')
c.execute('BEGIN EXCLUSIVE')
for i in range(2000): SQLiteMemoryStore._insert_audit(c,'memory_read',33)
os._exit(76)
"""
    assert subprocess.run([sys.executable, "-c", script, str(active.path)], cwd=API, timeout=30).returncode == 76
    assert Path(str(active.path) + "-journal").stat().st_size > 0
    monkeypatch.setattr(activation, "_point", lambda name: None)
    activation.recover_activation(active.path)
    assert marker(active.path) == 11
    with closing(sqlite3.connect(active.path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0] == 1


@pytest.mark.parametrize("damage", ["corrupt", "schema"])
def test_invalid_current_database_is_preserved_before_swap(pair, damage):
    active, _, _ = pair
    plan = plan_for(pair)
    if damage == "corrupt":
        active.path.write_bytes(b"synthetic current corruption")
    else:
        with active.transaction() as connection:
            connection.execute("UPDATE schema_migrations SET checksum=?", ("a" * 64,))
    before = active.path.read_bytes()
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    assert active.path.read_bytes() == before
    assert not leases.names(active.path)[3].exists()


def test_unexpected_sidecar_immediately_before_switch_prevents_replacement(pair, monkeypatch):
    active, _, _ = pair
    plan = plan_for(pair)
    def inject(name):
        if name == "switch:before":
            sidecar = Path(str(active.path) + "-wal")
            sidecar.write_bytes(b"synthetic unexpected sidecar")
            sidecar.chmod(0o600)
    monkeypatch.setattr(activation, "_point", inject)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    assert activation._state(active.path)["state"] == "PREPARED"
    assert marker(active.path) == 11


def test_parent_symlink_introduced_during_activation_blocks_switch(pair, monkeypatch):
    active, _, _ = pair
    plan = plan_for(pair)
    original_parent = active.path.parent
    moved_parent = original_parent.with_name("moved-synthetic-active")
    def inject(name):
        if name == "switch:before":
            original_parent.rename(moved_parent)
            original_parent.symlink_to(moved_parent, target_is_directory=True)
    monkeypatch.setattr(activation, "_point", inject)
    with pytest.raises(backup.BackupError):
        activation.activate(plan, plan.confirmation)
    assert marker(moved_parent / active.path.name) == 11
