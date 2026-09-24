from __future__ import annotations

import logging
import os
import sqlite3
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import backup_cli
import backup_recovery as backup
import pytest
from memory_models import (
    EntityRecord,
    EventRecord,
    ProvenanceRecord,
    RelationRecord,
    SourceRecord,
)
from memory_store import SQLiteMemoryStore

PASSPHRASE = "synthetic-only-backup-passphrase"
OTHER_PASSPHRASE = "synthetic-other-backup-passphrase"
MARKER = "synthetic-content-must-not-appear-in-archive"


def _store(tmp_path: Path, name: str = "source") -> SQLiteMemoryStore:
    directory = tmp_path / name
    directory.mkdir(mode=0o700)
    store = SQLiteMemoryStore(directory / "memory.sqlite3")
    store.initialize()
    return store


def _source(source_id: str = "src_synthetic_calendar") -> SourceRecord:
    return SourceRecord(
        id=source_id,
        provider="calendar_sim",
        resource_id="calendar:synthetic-primary",
        sync_status="disconnected",
    )


def _event(source_id: str, event_id: str, external_ref: str, *, title: str = MARKER) -> EventRecord:
    now = datetime.now(timezone.utc)
    return EventRecord(
        id=event_id,
        event_type="appointment",
        title=title,
        domain_id="dom_synthetic_a",
        occurred_at=now,
        payload_minimized={"marker": title},
        provenance=ProvenanceRecord(
            source_id=source_id,
            external_ref=external_ref,
            observed_at=now,
            last_verified_at=now,
            confidence=1.0,
            classification_method="human_review",
            classified_at=now,
        ),
    )


def _backup(store: SQLiteMemoryStore, tmp_path: Path, *, filename: str = "jarvis-backup-v1-test.jvb") -> Path:
    return backup.create_backup(
        store.path, tmp_path / "private-backups", PASSPHRASE, filename=filename
    )


def _database_rows(path: Path) -> dict[str, list[tuple]]:
    with sqlite3.connect(path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in tables
        }


def test_online_wal_backup_restores_complete_synthetic_database_without_plaintext(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    store.save_source(_source())
    event = store.save_event(_event("src_synthetic_calendar", "real_evt_synthetic_backup_a", "ref-a"))
    store.save_entity(EntityRecord(
        id="entity_synthetic_a", entity_type="appointment", name="Synthetic meeting",
        domain_id="dom_synthetic_a",
    ))
    store.save_entity(EntityRecord(
        id="entity_synthetic_b", entity_type="project", name="Synthetic project",
        domain_id="dom_synthetic_a",
    ))
    store.save_relation(RelationRecord(
        id="relation_synthetic_a", from_entity_id="entity_synthetic_a",
        to_entity_id="entity_synthetic_b", relation_type="related_to",
        domain_id="dom_synthetic_a", evidence_event_ids=(event.id,),
    ))
    store.record_audit("memory_read", 1)

    archive_path = _backup(store, tmp_path)
    validation_temp = tmp_path / "validation-temp"
    validation_temp.mkdir(mode=0o700)
    monkeypatch.setattr(backup.tempfile, "tempdir", str(validation_temp))
    archive = archive_path.read_bytes()
    source_image_before = store.path.read_bytes()
    assert MARKER.encode() not in archive
    assert PASSPHRASE.encode() not in archive
    assert stat.S_IMODE(archive_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive_path.parent.stat().st_mode) == 0o700
    assert store.path.read_bytes() == source_image_before

    restored_file = backup.restore_backup(
        archive_path, tmp_path / "restore-root", PASSPHRASE,
        destination_name="restore-v1-synthetic-roundtrip",
    )
    assert restored_file != store.path
    assert restored_file.parent != store.path.parent
    assert list(validation_temp.iterdir()) == []
    assert stat.S_IMODE(restored_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(restored_file.stat().st_mode) == 0o600
    assert sorted(item.name for item in restored_file.parent.parent.iterdir()) == [restored_file.parent.name]
    assert _database_rows(restored_file) == _database_rows(store.path)
    assert store.path.read_bytes() == source_image_before
    restored = SQLiteMemoryStore(restored_file)
    restored.initialize()
    with sqlite3.connect(restored_file) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM event_provenance").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM relation_evidence").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0] >= 5
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"sessions", "grants", "demo_events", "fixtures"} & names


def test_empty_database_stays_empty_and_demo_fixture_ids_are_not_imported(tmp_path):
    store = _store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        for table in ("sources", "events", "event_provenance", "entities", "relations", "audit_entries"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    archive = _backup(store, tmp_path)
    restored = backup.restore_backup(archive, tmp_path / "restore", PASSPHRASE)
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events WHERE id='evt_001'").fetchone()[0] == 0


def test_online_snapshot_is_consistent_during_concurrent_store_writes(tmp_path):
    store = _store(tmp_path)
    store.save_source(_source())
    started = threading.Event()

    def writer() -> None:
        started.set()
        for index in range(30):
            store.save_event(_event(
                "src_synthetic_calendar", f"real_evt_concurrent_{index}", f"concurrent-ref-{index}",
                title=f"synthetic concurrent {index}",
            ))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer)
        assert started.wait(timeout=2)
        archive = _backup(store, tmp_path)
        future.result(timeout=30)

    restored = backup.restore_backup(archive, tmp_path / "restore", PASSPHRASE)
    with sqlite3.connect(restored) as connection:
        events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        provenance = connection.execute("SELECT COUNT(*) FROM event_provenance").fetchone()[0]
        event_audits = connection.execute(
            "SELECT COUNT(*) FROM audit_entries WHERE operation='event_write'"
        ).fetchone()[0]
    assert 0 <= events <= 30
    assert provenance == events == event_audits


@pytest.mark.parametrize("mutation", ["ciphertext", "header", "truncate"])
def test_authentication_tampering_and_wrong_password_never_create_restore_target(tmp_path, mutation):
    store = _store(tmp_path)
    store.save_source(_source())
    store.save_event(_event("src_synthetic_calendar", "real_evt_auth_a", "auth-ref"))
    archive_path = _backup(store, tmp_path)
    original = archive_path.read_bytes()
    if mutation == "ciphertext":
        changed = original[:-1] + bytes([original[-1] ^ 1])
    elif mutation == "header":
        changed = original[:20] + bytes([original[20] ^ 1]) + original[21:]
    else:
        changed = original[:-9]
    archive_path.write_bytes(changed)
    restore_root = tmp_path / f"restore-{mutation}"
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive_path, restore_root, PASSPHRASE)
    assert not restore_root.exists()
    archive_path.write_bytes(original)
    with pytest.raises(backup.BackupAuthenticationError):
        backup.restore_backup(archive_path, restore_root, OTHER_PASSPHRASE)
    assert not restore_root.exists()


def test_decrypted_but_invalid_sqlite_is_rejected_before_restore_root_is_created(tmp_path):
    archive_dir = tmp_path / "private-archive"
    archive_dir.mkdir(mode=0o700)
    archive_path = archive_dir / "invalid.jvb"
    archive_path.write_bytes(backup._seal_snapshot(b"not a SQLite database", PASSPHRASE))
    os.chmod(archive_path, 0o600)
    restore_root = tmp_path / "restore"
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive_path, restore_root, PASSPHRASE)
    assert not restore_root.exists()


def test_validation_temp_directory_cannot_be_redirected_into_repository(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save_source(_source())
    archive = _backup(store, tmp_path)
    monkeypatch.setattr(backup.tempfile, "tempdir", str(backup.REPOSITORY_ROOT))
    restore_root = tmp_path / "restore"
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive, restore_root, PASSPHRASE)
    assert not restore_root.exists()


def test_validation_temp_directory_rejects_shared_writable_parent(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save_source(_source())
    archive = _backup(store, tmp_path)
    shared_temp = tmp_path / "shared-temp"
    shared_temp.mkdir(mode=0o700)
    os.chmod(shared_temp, 0o777)
    monkeypatch.setattr(backup.tempfile, "tempdir", str(shared_temp))
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive, tmp_path / "restore", PASSPHRASE)
    assert list(shared_temp.iterdir()) == []


def test_invalid_schema_snapshot_is_rejected_without_changing_archive_or_destination(tmp_path):
    store = _store(tmp_path)
    store.save_source(_source())
    store.save_event(_event("src_synthetic_calendar", "real_evt_bad_schema", "bad-schema"))
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE audit_entries")
    with sqlite3.connect(store.path) as connection:
        image = connection.serialize()
    archive_dir = tmp_path / "private-archive"
    archive_dir.mkdir(mode=0o700)
    archive_path = archive_dir / "bad-schema.jvb"
    raw = backup._seal_snapshot(image, PASSPHRASE)
    archive_path.write_bytes(raw)
    os.chmod(archive_path, 0o600)
    restore_root = tmp_path / "restore"
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive_path, restore_root, PASSPHRASE)
    assert archive_path.read_bytes() == raw
    assert not restore_root.exists()


def test_backup_collision_preserves_original_and_leaves_no_partial_file(tmp_path):
    store = _store(tmp_path)
    store.save_source(_source())
    archive = _backup(store, tmp_path)
    before = archive.read_bytes()
    with pytest.raises(backup.BackupCollisionError):
        backup.create_backup(store.path, archive.parent, PASSPHRASE, filename=archive.name)
    assert archive.read_bytes() == before
    assert list(archive.parent.iterdir()) == [archive]


def test_existing_restore_destination_is_untouched_and_path_traversal_is_rejected(tmp_path):
    store = _store(tmp_path)
    store.save_source(_source())
    archive = _backup(store, tmp_path)
    root = tmp_path / "restore-root"
    root.mkdir(mode=0o700)
    existing = root / "restore-v1-existing"
    existing.mkdir(mode=0o700)
    marker = existing / "keep.txt"
    marker.write_text("synthetic-preserve")
    os.chmod(marker, 0o600)
    with pytest.raises(backup.RestoreDestinationError):
        backup.restore_backup(archive, root, PASSPHRASE, destination_name=existing.name)
    with pytest.raises(backup.RestoreDestinationError):
        backup.restore_backup(archive, root, PASSPHRASE, destination_name="../escape")
    assert marker.read_text() == "synthetic-preserve"
    assert sorted(path.name for path in root.iterdir()) == ["restore-v1-existing"]


def test_symlink_sources_archives_and_output_directories_are_rejected(tmp_path):
    store = _store(tmp_path)
    store.save_source(_source())
    outside = tmp_path / "outside.sqlite3"
    outside.write_bytes(store.path.read_bytes())
    os.chmod(outside, 0o600)
    source_link = tmp_path / "source-link.sqlite3"
    source_link.symlink_to(outside)
    with pytest.raises(backup.BackupError):
        backup.create_backup(source_link, tmp_path / "out", PASSPHRASE)

    archive = _backup(store, tmp_path)
    archive_link = archive.parent / "linked.jvb"
    archive_link.symlink_to(archive)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive_link, tmp_path / "restore", PASSPHRASE)

    link_directory = tmp_path / "out-link"
    link_directory.symlink_to(archive.parent, target_is_directory=True)
    with pytest.raises(backup.BackupError):
        backup.create_backup(store.path, link_directory, PASSPHRASE)
    restore_link = tmp_path / "restore-link"
    restore_link.symlink_to(archive.parent, target_is_directory=True)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive, restore_link, PASSPHRASE)


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_symlinked_sqlite_sidecars_are_rejected(tmp_path, suffix):
    store = _store(tmp_path)
    store.save_source(_source())
    sidecar = Path(f"{store.path}{suffix}")
    sidecar.unlink(missing_ok=True)
    target = tmp_path / f"external-sidecar{suffix}"
    target.write_bytes(b"synthetic")
    os.chmod(target, 0o600)
    sidecar.symlink_to(target)
    with pytest.raises(backup.BackupError):
        backup.create_backup(store.path, tmp_path / "out", PASSPHRASE)


def test_failed_backup_write_and_restore_write_are_clean_and_do_not_leak_secrets(tmp_path, monkeypatch, caplog):
    store = _store(tmp_path)
    store.save_source(_source())
    store.save_event(_event("src_synthetic_calendar", "real_evt_write_fail", "write-ref"))
    caplog.set_level(logging.DEBUG)
    source_before = _database_rows(store.path)

    def fail_write(fd: int, payload: bytes) -> None:
        raise OSError("synthetic low-level failure with " + PASSPHRASE)

    monkeypatch.setattr(backup, "_write_all", fail_write)
    backup_directory = tmp_path / "write-failure-backups"
    with pytest.raises(backup.BackupError) as caught:
        backup.create_backup(store.path, backup_directory, PASSPHRASE)
    assert PASSPHRASE not in str(caught.value)
    assert PASSPHRASE not in caplog.text
    assert list(backup_directory.iterdir()) == []
    assert _database_rows(store.path) == source_before

    monkeypatch.undo()
    archive = _backup(store, tmp_path)
    monkeypatch.setattr(backup, "_write_all", fail_write)
    restore_root = tmp_path / "restore-write-failure"
    with pytest.raises(backup.BackupError) as caught:
        backup.restore_backup(archive, restore_root, PASSPHRASE)
    assert PASSPHRASE not in str(caught.value)
    assert not restore_root.exists() or not list(restore_root.iterdir())
    assert PASSPHRASE not in caplog.text


def test_failure_after_publication_rolls_back_new_restore_files(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save_source(_source())
    archive = _backup(store, tmp_path)
    restore_root = tmp_path / "restore-fsync-failure"

    def fail_sync(_path: Path) -> None:
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(backup, "_fsync_directory", fail_sync)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive, restore_root, PASSPHRASE)
    assert not restore_root.exists() or not list(restore_root.iterdir())


def test_source_wal_sidecar_permissions_and_password_constraints(tmp_path):
    store = _store(tmp_path)
    store.save_source(_source())
    wal = Path(f"{store.path}-wal")
    wal.write_bytes(b"synthetic")
    os.chmod(wal, 0o644)
    with pytest.raises(backup.BackupError):
        backup.create_backup(store.path, tmp_path / "out", PASSPHRASE)
    wal.unlink()
    with pytest.raises(backup.BackupError):
        backup.create_backup(store.path, tmp_path / "out", "short")
    with pytest.raises(backup.BackupError):
        backup.create_backup(store.path, tmp_path / "out", "x" * 1025)


def test_cli_has_no_password_argument_and_rejects_noninteractive_usage(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        backup_cli.run(["backup", "--password", "synthetic-secret"])
    invalid_args = capsys.readouterr()
    assert "synthetic-secret" not in invalid_args.out + invalid_args.err
    monkeypatch.setattr(backup_cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(backup_cli.sys.stderr, "isatty", lambda: False)
    assert backup_cli.run(["backup"]) == 2
    captured = capsys.readouterr()
    assert "terminal" in captured.err
    assert "synthetic-secret" not in captured.out + captured.err


def test_cli_restore_accepts_only_basename_under_private_backup_root(monkeypatch, tmp_path, capsys):
    fake_database = tmp_path / "synthetic" / "memory.sqlite3"
    monkeypatch.setattr(backup_cli, "default_database_path", lambda: fake_database)
    monkeypatch.setattr(backup_cli, "_prompt_passphrase", lambda *, confirm: PASSPHRASE)
    observed = {}

    def fake_restore(source, root, passphrase):
        observed.update(source=source, root=root, passphrase=passphrase)
        return tmp_path / "synthetic" / "restores" / "restore-v1-x" / "memory.sqlite3"

    monkeypatch.setattr(backup_cli, "restore_backup", fake_restore)
    assert backup_cli.run(["restore", "jarvis-backup-v1-synthetic.jvb"]) == 0
    assert observed["source"] == tmp_path / "synthetic" / "backups" / "jarvis-backup-v1-synthetic.jvb"
    assert observed["root"] == tmp_path / "synthetic" / "restores"
    assert observed["passphrase"] == PASSPHRASE
    assert "synthetic-secret" not in capsys.readouterr().out

    assert backup_cli.run(["restore", "../jarvis-backup-v1-synthetic.jvb"]) == 2


def test_cli_end_to_end_uses_terminal_prompts_and_restores_to_isolated_default_root(
    monkeypatch, tmp_path, capsys
):
    store = _store(tmp_path)
    store.save_source(_source())
    store.save_event(_event("src_synthetic_calendar", "real_evt_cli_a", "cli-ref"))
    source_before = store.path.read_bytes()
    monkeypatch.setattr(backup_cli, "default_database_path", lambda: store.path)
    monkeypatch.setattr(backup_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(backup_cli.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(backup_cli.getpass, "getpass", lambda _prompt: PASSPHRASE)

    assert backup_cli.run(["backup"]) == 0
    backup_output = capsys.readouterr().out
    filename = backup_output.split(": ", 1)[1].strip()
    assert filename.startswith("jarvis-backup-v1-") and filename.endswith(".jvb")
    archive = store.path.parent / "backups" / filename
    assert archive.is_file()
    assert store.path.read_bytes() == source_before

    assert backup_cli.run(["restore", filename]) == 0
    restored_output = capsys.readouterr().out
    assert "restaurado isoladamente" in restored_output
    restore_root = store.path.parent / "restores"
    restored_directories = list(restore_root.iterdir())
    assert len(restored_directories) == 1
    restored = restored_directories[0] / "memory.sqlite3"
    assert restored != store.path
    assert _database_rows(restored) == _database_rows(store.path)
    assert store.path.read_bytes() == source_before


def test_backup_and_restore_do_not_expose_any_http_routes():
    from main import create_app
    from server_config import LocalServerConfig

    app = create_app(LocalServerConfig(host="127.0.0.1", port=8000))
    paths = set(app.openapi().get("paths", {}))
    assert not any("backup" in path or "restore" in path for path in paths)


def test_backup_rejects_database_inside_repository_before_reading_it(tmp_path):
    repo_file = Path(__file__).resolve().parents[2] / "synthetic-forbidden.sqlite3"
    with pytest.raises(backup.BackupError):
        backup.create_backup(repo_file, tmp_path / "backup", PASSPHRASE)


def test_backup_of_missing_source_does_not_initialize_or_create_it(tmp_path):
    source = tmp_path / "not-created" / "memory.sqlite3"
    with pytest.raises(backup.BackupError):
        backup.create_backup(source, tmp_path / "backup", PASSPHRASE)
    assert not source.exists()
    assert not source.parent.exists()
