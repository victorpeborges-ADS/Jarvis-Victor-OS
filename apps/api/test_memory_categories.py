"""J11: categorias de memória separadas, em banco temporário."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile

import pytest

from backup_cli import _parser as backup_cli_parser
from backup_recovery import LegacyDeletionConfirmationRequired, create_backup, restore_backup
from local_captures import create_capture, delete_capture, search_captures
from memory_deletions import MemoryRevisionConflict, apply_deletion_tombstones, write_tombstone
from memory_categories import delete_memory, list_memory, page_memory, read_memory, record_memory, revise_memory
from memory_store import MIGRATIONS_DIR, SQLiteMemoryStore

BACKUP_PASSPHRASE = "sintetica-backup-local"

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 21, 18, 5, tzinfo=timezone.utc)


def test_cli_requires_an_explicit_legacy_resurrection_flag():
    parser = backup_cli_parser()
    old_backup = parser.parse_args(["restore", "jarvis-backup-v1-old.jvb"])
    confirmed_backup = parser.parse_args([
        "restore", "jarvis-backup-v1-old.jvb", "--confirm-legacy-resurrection",
    ])
    assert old_backup.confirm_legacy_resurrection is False
    assert confirmed_backup.confirm_legacy_resurrection is True


def _store(path: Path, encrypted_store_factory) -> SQLiteMemoryStore:
    store = encrypted_store_factory(path)
    store.initialize()
    return store


def test_categories_stay_in_separate_tables(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    fact = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "prefere texto curto", "owner_confirmation", "owner-note", NOW,
    )
    evidence = record_memory(
        store, "owner", "dom_synthetic_a", "external_evidence",
        "fonte sintetica cita prazo", "synthetic_source", "fixture-prazo", NOW,
    )
    proposal = record_memory(
        store, "owner", "dom_synthetic_a", "inferred_proposal",
        "talvez adiar a revisao", "assistant_inference", "turn-1", NOW,
    )
    facts = list_memory(store, "owner", "dom_synthetic_a", "confirmed_fact")
    assert [item["id"] for item in facts] == [fact["id"]]
    assert facts[0]["source_kind"] == "owner_confirmation"
    assert facts[0]["version"] == 1
    assert [item["id"] for item in list_memory(store, "owner", "dom_synthetic_a", "external_evidence")] == [evidence["id"]]
    assert [item["id"] for item in list_memory(store, "owner", "dom_synthetic_a", "inferred_proposal")] == [proposal["id"]]
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM local_captures").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM confirmed_facts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM external_evidence").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM inferred_proposals").fetchone()[0] == 1


def test_other_domain_cannot_read_or_revise(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    fact = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "fato do dominio a", "owner_confirmation", "owner-note", NOW,
    )
    assert list_memory(store, "owner", "dom_synthetic_b", "confirmed_fact") == []
    with pytest.raises(ValueError, match="memória recusada"):
        read_memory(store, "owner", "dom_synthetic_b", "confirmed_fact", fact["id"])
    with pytest.raises(ValueError, match="memória recusada"):
        revise_memory(
            store, "owner", "dom_synthetic_b", "confirmed_fact", fact["id"], "texto alheio", LATER,
        )
    assert read_memory(store, "owner", "dom_synthetic_a", "confirmed_fact", fact["id"])["body"] == "fato do dominio a"


def test_assistant_reply_does_not_become_a_confirmed_fact(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    with pytest.raises(ValueError, match="memória recusada"):
        record_memory(
            store, "owner", "dom_synthetic_a", "confirmed_fact",
            "o assistente afirmou isto", "assistant_reply", "turn-9", NOW,
        )
    with pytest.raises(ValueError, match="memória recusada"):
        record_memory(
            store, "owner", "dom_synthetic_a", "confirmed_fact",
            "inferencia promovida", "assistant_inference", "turn-9", NOW,
        )
    with pytest.raises(ValueError, match="memória recusada"):
        record_memory(
            store, "owner", "dom_synthetic_a", "explicit_capture",
            "nao e linha daqui", "owner_confirmation", "owner-note", NOW,
        )
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_facts").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO confirmed_facts(
                       id, owner, domain_id, body, source_kind, source_ref,
                       version, recorded_at, revised_at
                   ) VALUES (?, 'owner', 'dom_synthetic_a', 'fato', 'assistant_reply', 'turn-9', 1, ?, ?)""",
                ("ab" * 16, NOW.isoformat(), NOW.isoformat()),
            )


def test_capture_remains_outside_the_category_tables(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    create_capture(store, "owner", "ideia explicita", NOW)
    record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "preferencia confirmada", "owner_confirmation", "owner-note", NOW,
    )
    with store.transaction() as connection:
        assert connection.execute("SELECT body FROM local_captures").fetchone()[0] == "ideia explicita"
        assert connection.execute("SELECT body FROM confirmed_facts").fetchone()[0] == "preferencia confirmada"


def test_capture_delete_purges_search_and_writes_content_free_tombstone(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    capture = create_capture(store, "owner", "canario sintético para apagar", NOW)
    deleted = delete_capture(store, "owner", capture["id"], expected_revision=1)
    assert search_captures(store, "owner", "canario") == ([], 0)
    repeated = delete_capture(store, "owner", capture["id"], expected_revision=1)
    assert repeated["operation_id"] == deleted["operation_id"]
    assert repeated["idempotent"] is True
    with store.transaction() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(memory_deletion_tombstones)")}
        assert "body" not in columns
        tombstone = connection.execute(
            "SELECT category, domain_id, deleted_revision, operation_id FROM memory_deletion_tombstones WHERE record_id = ?",
            (capture["id"],),
        ).fetchone()
    assert tuple(tombstone) == (
        "explicit_capture", "dom_synthetic_a", 1, deleted["operation_id"],
    )


def test_revision_keeps_origin_and_steps_version(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = record_memory(
        store, "owner", "dom_synthetic_a", "external_evidence",
        "trecho original", "synthetic_source", "fixture-prazo", NOW,
    )
    revised = revise_memory(
        store, "owner", "dom_synthetic_a", "external_evidence",
        created["id"], "trecho corrigido", LATER,
    )
    assert revised["version"] == 2
    assert revised["source_kind"] == "synthetic_source"
    assert revised["source_ref"] == "fixture-prazo"
    assert revised["recorded_at"] == created["recorded_at"]
    assert revised["body"] == "trecho corrigido"
    with pytest.raises(ValueError, match="memória recusada"):
        revise_memory(
            store, "owner", "dom_synthetic_a", "confirmed_fact", created["id"], "promovido", LATER,
        )


def test_delete_in_another_domain_keeps_the_row(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    fact = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "fato que permanece", "owner_confirmation", "owner-note", NOW,
    )
    with pytest.raises(ValueError, match="memória recusada"):
        delete_memory(store, "owner", "dom_synthetic_b", "confirmed_fact", fact["id"])
    assert read_memory(store, "owner", "dom_synthetic_a", "confirmed_fact", fact["id"])["body"] == "fato que permanece"


def test_open_database_delete_leaves_the_prior_backup(tmp_path, encrypted_store_factory):
    path = tmp_path / "daily" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    created = [
        record_memory(
            store, "owner", "dom_synthetic_a", category, text, source_kind, source_ref, NOW,
        )
        for category, source_kind, source_ref, text in (
            ("confirmed_fact", "owner_confirmation", "owner-note", "fato que sai"),
            ("external_evidence", "synthetic_source", "fixture-prazo", "evidencia que sai"),
            ("inferred_proposal", "assistant_inference", "turn-1", "proposta que sai"),
        )
    ]
    archive = create_backup(path, tmp_path / "backups", BACKUP_PASSPHRASE, storage_key=encrypted_store_factory.storage_key)
    original_archive = archive.read_bytes()
    for record in created:
        result = delete_memory(
            store, "owner", record["domain_id"], record["category"], record["id"],
        )
        assert result == {
            "id": record["id"],
            "category": record["category"],
            "domain_id": "dom_synthetic_a",
            "deleted_revision": 1,
            "operation_id": result["operation_id"],
            "removed_from_open_database": True,
            "historical_backup_may_keep_text": True,
        }
        with pytest.raises(ValueError, match="memória recusada"):
            read_memory(store, "owner", "dom_synthetic_a", record["category"], record["id"])
    assert archive.is_file()
    with pytest.raises(LegacyDeletionConfirmationRequired):
        restore_backup(
            archive, tmp_path / "restores", BACKUP_PASSPHRASE, storage_key=encrypted_store_factory.storage_key,
        )
    assert archive.read_bytes() == original_archive
    restored = restore_backup(
        archive, tmp_path / "restores", BACKUP_PASSPHRASE,
        storage_key=encrypted_store_factory.storage_key,
        confirm_legacy_resurrection=True,
    )
    restored_store = encrypted_store_factory(restored)
    restored_store.initialize()
    assert archive.read_bytes() == original_archive
    for record in created:
        assert read_memory(
            restored_store, "owner", "dom_synthetic_a", record["category"], record["id"],
        )["body"] == record["body"]
        with pytest.raises(ValueError, match="memória recusada"):
            read_memory(store, "owner", "dom_synthetic_a", record["category"], record["id"])


def test_delete_replay_is_idempotent_and_stale_revision_conflicts(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "fato para apagar", "owner_confirmation", "owner-note", NOW,
    )
    deleted = delete_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact", created["id"], expected_revision=1,
    )
    repeated = delete_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact", created["id"], expected_revision=1,
    )
    assert repeated["idempotent"] is True
    assert repeated["operation_id"] == deleted["operation_id"]
    with pytest.raises(MemoryRevisionConflict):
        delete_memory(
            store, "owner", "dom_synthetic_a", "confirmed_fact", created["id"], expected_revision=2,
        )


@pytest.mark.parametrize("category,kind", [
    ("explicit_capture", "user_authored_capture"),
    ("confirmed_fact", "owner_confirmation"),
    ("external_evidence", "synthetic_source"),
    ("inferred_proposal", "assistant_inference"),
])
def test_new_backup_carries_tombstones_and_restore_applies_them(tmp_path, encrypted_store_factory, category, kind):
    path = tmp_path / "private" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    text = "canario de exclusao sintetico"
    if category == "explicit_capture":
        created = create_capture(store, "owner", text, NOW)
        deleted = delete_capture(store, "owner", created["id"], expected_revision=1)
        table = "local_captures"
    else:
        created = record_memory(store, "owner", "dom_synthetic_a", category, text, kind, "owner-note", NOW)
        deleted = delete_memory(store, "owner", "dom_synthetic_a", category, created["id"], expected_revision=1)
        table = {"confirmed_fact": "confirmed_facts", "external_evidence": "external_evidence",
                 "inferred_proposal": "inferred_proposals"}[category]
    # Deliberately build a stale synthetic image with a row AND its known
    # deletion decision. Restore must replay, not merely preserve an empty DB.
    with store.transaction() as connection:
        if category == "explicit_capture":
            connection.execute(
                """INSERT INTO local_captures(id, owner, domain_id, body, created_at, revised_at)
                   VALUES (?, 'owner', 'dom_synthetic_a', ?, ?, ?)""",
                (created["id"], text, NOW.isoformat(), NOW.isoformat()),
            )
        else:
            connection.execute(
                f"""INSERT INTO {table}(id, owner, domain_id, body, source_kind, source_ref,
                       version, recorded_at, revised_at)
                    VALUES (?, 'owner', 'dom_synthetic_a', ?, ?, 'owner-note', 1, ?, ?)""",
                (created["id"], text, kind, NOW.isoformat(), NOW.isoformat()),
            )
    archive = create_backup(path, tmp_path / "backups", BACKUP_PASSPHRASE, storage_key=encrypted_store_factory.storage_key)
    restored = restore_backup(archive, tmp_path / "restores", BACKUP_PASSPHRASE, storage_key=encrypted_store_factory.storage_key)
    restored_store = encrypted_store_factory(restored)
    restored_store.initialize()
    restored_store.initialize()
    with restored_store.transaction() as connection:
        tombstone = connection.execute(
            "SELECT deleted_revision, operation_id FROM memory_deletion_tombstones WHERE record_id = ?",
            (created["id"],),
        ).fetchone()
    assert tuple(tombstone) == (1, deleted["operation_id"])
    assert page_memory(restored_store, "owner", "dom_synthetic_a", category, 0) is None


def test_capture_page_reads_previously_empty_revision_timestamp(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = create_capture(store, "owner", "captura sintética", NOW)
    with store.transaction() as connection:
        connection.execute("UPDATE local_captures SET revised_at = '' WHERE id = ?", (created["id"],))
    item = page_memory(store, "owner", "dom_synthetic_a", "explicit_capture", 0)
    assert item["revised_at"] == item["recorded_at"] == created["created_at"]


def test_restore_does_not_know_deletions_made_after_its_snapshot(tmp_path, encrypted_store_factory):
    path = tmp_path / "private" / "memory.sqlite3"
    store = _store(path, encrypted_store_factory)
    older = create_capture(store, "owner", "exclusão anterior", NOW)
    delete_capture(store, "owner", older["id"], expected_revision=1)
    newer = create_capture(store, "owner", "exclusão posterior ao backup", LATER)
    archive = create_backup(path, tmp_path / "backups", BACKUP_PASSPHRASE,
                            storage_key=encrypted_store_factory.storage_key)
    delete_capture(store, "owner", newer["id"], expected_revision=1)
    restored = restore_backup(archive, tmp_path / "restores", BACKUP_PASSPHRASE,
                              storage_key=encrypted_store_factory.storage_key)
    restored_store = encrypted_store_factory(restored)
    restored_store.initialize()
    # This is a documented limitation: isolated restore has no active-ledger merge.
    assert page_memory(restored_store, "owner", "dom_synthetic_a", "explicit_capture", 0)["id"] == newer["id"]
    assert page_memory(store, "owner", "dom_synthetic_a", "explicit_capture", 0) is None


def test_tombstone_same_revision_with_different_content_is_a_conflict(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    created = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "conteudo original", "owner_confirmation", "owner-note", NOW,
    )
    with store.transaction() as connection:
        write_tombstone(
            connection, category="confirmed_fact", domain_id="dom_synthetic_a", record_id=created["id"],
            revision=1, body="conteudo diferente na mesma revisao", deleted_at=NOW,
        )
        with pytest.raises(MemoryRevisionConflict, match="incompatível"):
            apply_deletion_tombstones(connection)
        assert connection.execute("SELECT COUNT(*) FROM confirmed_facts WHERE id = ?", (created["id"],)).fetchone()[0] == 1


def test_upgrade_adds_empty_category_tables(tmp_path, encrypted_store_factory):
    older = tmp_path / "older-migrations"
    older.mkdir()
    for migration in MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"):
        if migration.name != "0022_memory_categories.sql":
            copyfile(migration, older / migration.name)
    path = tmp_path / "private" / "memory.sqlite3"
    encrypted_store_factory(path, migrations_dir=older).initialize()
    upgraded = encrypted_store_factory(path)
    upgraded.initialize()
    with upgraded.transaction() as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()[0] == "0027_memory_capture_revisions"
        for table in ("confirmed_facts", "external_evidence", "inferred_proposals"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
