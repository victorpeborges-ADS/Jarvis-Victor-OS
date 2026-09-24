import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from main import create_app
from memory_models import (
    AuditRecord,
    EntityRecord,
    EventRecord,
    ProvenanceRecord,
    ReadScope,
    RelationRecord,
    SourceRecord,
)
from memory_store import DatabaseCorruptError, MigrationError, MIGRATIONS_DIR, SQLiteMemoryStore, REPOSITORY_ROOT, default_database_path
from server_config import LocalServerConfig


def now() -> datetime:
    return datetime.now(timezone.utc)


def make_source(source_id: str = "src_test_calendar") -> SourceRecord:
    return SourceRecord(
        id=source_id,
        provider="calendar_sim",
        resource_id="calendar:synthetic-primary",
        sync_status="disconnected",
    )


def make_event(
    source_id: str = "src_test_calendar",
    event_id: str = "synthetic_event_a",
    domain_id: str | None = "dom_synthetic_a",
    external_ref: str | None = "synthetic-ref-a",
) -> EventRecord:
    observed = now()
    return EventRecord(
        id=event_id,
        event_type="appointment",
        title="Ensaio sintético",
        domain_id=domain_id,
        sensitivity="normal",
        occurred_at=observed,
        payload_minimized={"test_marker": "synthetic-only"},
        provenance=ProvenanceRecord(
            source_id=source_id,
            external_ref=external_ref,
            observed_at=observed,
            last_verified_at=observed,
            confidence=0.9,
            classification_method="human_review" if domain_id else "unclassified",
            classified_at=observed if domain_id else None,
        ),
    )


def initialized_store(tmp_path, *, migration_dir=None) -> SQLiteMemoryStore:
    store = SQLiteMemoryStore(tmp_path / "private" / "memory.sqlite3", migrations_dir=migration_dir)
    store.initialize()
    return store


def add_source_and_event(store: SQLiteMemoryStore, event: EventRecord | None = None) -> EventRecord:
    source = make_source()
    store.save_source(source)
    return store.save_event(event or make_event(source_id=source.id))


def scope(domain_id: str = "dom_synthetic_a") -> list[ReadScope]:
    return [ReadScope(
        connector="calendar_sim",
        resource_id="calendar:synthetic-primary",
        domain_ids=frozenset({domain_id}),
    )]


def test_empty_database_migrates_once_uses_wal_and_private_permissions(tmp_path):
    store = initialized_store(tmp_path)
    store.initialize()
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [
            ("0001_initial",), ("0002_audit_and_relation_domain",)
        ]
        for table in ("sources", "events", "event_provenance", "entities", "relations", "relation_evidence", "audit_entries"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_default_database_path_is_outside_repository_and_repo_path_is_rejected(tmp_path):
    assert REPOSITORY_ROOT not in default_database_path().parents
    with pytest.raises(ValueError, match="fora do repositório"):
        SQLiteMemoryStore(REPOSITORY_ROOT / "should-never-exist.sqlite3")


def test_database_from_previous_migration_version_upgrades_without_replaying_ddl(tmp_path):
    previous_migrations = tmp_path / "previous_migrations"
    previous_migrations.mkdir()
    copyfile(MIGRATIONS_DIR / "0001_initial.sql", previous_migrations / "0001_initial.sql")
    database_path = tmp_path / "private" / "memory.sqlite3"
    SQLiteMemoryStore(database_path, migrations_dir=previous_migrations).initialize()

    SQLiteMemoryStore(database_path).initialize()
    with sqlite3.connect(database_path) as connection:
        versions = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(relations)")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert versions == [("0001_initial",), ("0002_audit_and_relation_domain",)]
    assert "domain_id" in columns
    assert "audit_entries" in tables


def test_existing_shared_directory_is_rejected_without_changing_its_permissions(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    store = SQLiteMemoryStore(shared / "memory.sqlite3")
    with pytest.raises(PermissionError, match="permissões privadas"):
        store.initialize()
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755
    assert not store.path.exists()


def test_database_path_symlink_is_rejected_even_when_target_is_missing(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    link = private / "memory.sqlite3"
    link.symlink_to(private / "not-created.sqlite3")
    with pytest.raises(ValueError, match="link simbólico"):
        SQLiteMemoryStore(link)


def test_migration_failure_rolls_back_ddl_and_does_not_mark_version(tmp_path):
    migration_dir = tmp_path / "broken_migrations"
    migration_dir.mkdir()
    (migration_dir / "0001_broken.sql").write_text(
        "CREATE TABLE partial_table (id INTEGER PRIMARY KEY);\n"
        "CREATE TABL invalid_syntax (id INTEGER);\n",
        encoding="utf-8",
    )
    store = SQLiteMemoryStore(tmp_path / "private" / "memory.sqlite3", migrations_dir=migration_dir)
    with pytest.raises(MigrationError, match="revertida"):
        store.initialize()
    with sqlite3.connect(store.path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "partial_table" not in names
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_corrupt_database_fails_closed(tmp_path):
    path = tmp_path / "private" / "memory.sqlite3"
    path.parent.mkdir(mode=0o700)
    path.write_bytes(b"not a SQLite database")
    store = SQLiteMemoryStore(path)
    with pytest.raises(DatabaseCorruptError):
        store.initialize()


def test_corrupt_database_prevents_app_lifespan_from_serving(tmp_path):
    path = tmp_path / "private" / "memory.sqlite3"
    path.parent.mkdir(mode=0o700)
    path.write_bytes(b"corrupted database")
    app = create_app(LocalServerConfig(), database_path=path)
    with pytest.raises(DatabaseCorruptError):
        with TestClient(app):
            pytest.fail("a API não deve servir antes de inicializar o banco")


def test_interrupted_transaction_rolls_back_and_reopened_store_keeps_committed_data(tmp_path):
    store = initialized_store(tmp_path)
    source = make_source()
    store.save_source(source)
    event = make_event(source_id=source.id)
    store.save_event(event)

    with pytest.raises(RuntimeError, match="interrompida"):
        with store.transaction() as connection:
            connection.execute("DELETE FROM events WHERE id=?", (event.id,))
            raise RuntimeError("transação interrompida")

    reopened = SQLiteMemoryStore(store.path)
    reopened.initialize()
    found = reopened.list_authorized_events(scope())
    assert [item.event.id for item in found] == [event.id]


def test_committed_synthetic_event_survives_a_real_process_restart(tmp_path):
    store = initialized_store(tmp_path)
    event = add_source_and_event(store)
    child_code = (
        "import sys; from memory_store import SQLiteMemoryStore; from memory_models import ReadScope; "
        "store=SQLiteMemoryStore(sys.argv[1]); store.initialize(); "
        "scope=ReadScope(connector='calendar_sim',resource_id='calendar:synthetic-primary',domain_ids=frozenset({'dom_synthetic_a'})); "
        "print(','.join(item.event.id for item in store.list_authorized_events([scope])))"
    )
    restarted = subprocess.run(
        [sys.executable, "-c", child_code, str(store.path)],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=True,
    )
    assert restarted.stdout.strip() == event.id


def test_duplicate_external_event_is_idempotent_and_updates_one_record(tmp_path):
    store = initialized_store(tmp_path)
    source = make_source()
    store.save_source(source)
    first = make_event(source_id=source.id, event_id="synthetic_event_first")
    store.save_event(first)
    duplicate = make_event(source_id=source.id, event_id="synthetic_event_duplicate")
    duplicate = duplicate.model_copy(update={"title": "Atualização sintética"})
    result = store.save_event(duplicate)

    records = store.list_authorized_events(scope())
    assert result.id == first.id
    assert len(records) == 1
    assert records[0].event.title == "Atualização sintética"


def test_audit_trail_contains_only_allowlisted_operation_and_count(tmp_path):
    store = initialized_store(tmp_path)
    event = add_source_and_event(store)
    assert store.list_authorized_events(scope())
    store.get_authorized_event(event.id, scope())

    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT operation, outcome, record_count, dataset FROM audit_entries ORDER BY rowid"
        ).fetchall()
    assert [row[0] for row in rows] == ["source_write", "event_write", "memory_read", "memory_read"]
    assert [row[2] for row in rows] == [0, 0, 1, 1]
    assert all(row[1] == "success" and row[3] == "real" for row in rows)
    assert event.id not in repr(rows)
    assert event.title not in repr(rows)
    with pytest.raises(ValidationError):
        AuditRecord(operation="arbitrary", record_count=1)


def test_invalid_models_and_malformed_stored_payload_fail_closed(tmp_path, caplog):
    store = initialized_store(tmp_path)
    source = make_source()
    store.save_source(source)
    with pytest.raises(ValidationError):
        EventRecord.model_validate({
            "id": "bad_domain", "event_type": "appointment", "title": "malformed synthetic",
            "domain_id": "dom_unknown", "provenance": {
                "source_id": source.id, "observed_at": now(),
                "classification_method": "human_review", "classified_at": now(),
            },
        })
    with pytest.raises(ValidationError):
        EventRecord.model_validate({
            "id": "bad_time", "event_type": "appointment", "title": "naive time",
            "domain_id": "dom_synthetic_a", "provenance": {
                "source_id": source.id, "observed_at": datetime.now(),
                "classification_method": "human_review", "classified_at": now(),
            },
        })

    event = store.save_event(make_event(source_id=source.id))
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE events SET payload_json='{' WHERE id=?", (event.id,))
        connection.commit()
    assert store.list_authorized_events(scope()) == []
    assert store.get_authorized_event(event.id, scope()) is None
    assert "Ignoring malformed row" in caplog.text
    assert event.title not in caplog.text


def test_corrupted_unknown_domain_cannot_leak_into_another_scope(tmp_path):
    store = initialized_store(tmp_path)
    source = make_source()
    store.save_source(source)
    event_a = store.save_event(make_event(source_id=source.id, event_id="synthetic_event_a", domain_id="dom_synthetic_a"))
    event_b = store.save_event(make_event(source_id=source.id, event_id="synthetic_event_b", domain_id="dom_synthetic_b", external_ref="synthetic-ref-b"))
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE events SET domain_id='dom_unknown' WHERE id=?", (event_a.id,))
        connection.commit()
    assert store.list_authorized_events(scope("dom_synthetic_a")) == []
    assert store.get_authorized_event(event_a.id, scope("dom_synthetic_a")) is None
    assert [record.event.id for record in store.list_authorized_events(scope("dom_synthetic_b"))] == [event_b.id]


def test_source_event_provenance_entity_and_relation_foreign_keys(tmp_path):
    store = initialized_store(tmp_path)
    source = store.save_source(make_source())
    event = store.save_event(make_event(source_id=source.id))
    first = store.save_entity(EntityRecord(id="entity_synthetic_a", entity_type="project", name="Projeto sintético", domain_id="dom_synthetic_a"))
    second = store.save_entity(EntityRecord(id="entity_synthetic_b", entity_type="task", name="Tarefa sintética", domain_id="dom_synthetic_a"))
    relation = RelationRecord(
        id="relation_synthetic_a", from_entity_id=first.id, to_entity_id=second.id,
        relation_type="supports", domain_id="dom_synthetic_a", evidence_event_ids=(event.id,),
    )
    store.save_relation(relation)

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM event_provenance WHERE event_id=?", (event.id,)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM relation_evidence WHERE relation_id=? AND event_id=?", (relation.id, event.id)).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    broken = relation.model_copy(update={"id": "relation_missing_evidence", "evidence_event_ids": ("missing",)})
    with pytest.raises(sqlite3.IntegrityError):
        store.save_relation(broken)

    other_event = store.save_event(make_event(source_id=source.id, event_id="synthetic_event_b", domain_id="dom_synthetic_b", external_ref="synthetic-ref-b"))
    other_entity = store.save_entity(EntityRecord(id="entity_synthetic_c", entity_type="project", name="Outro projeto", domain_id="dom_synthetic_b"))
    cross_domain_relation = RelationRecord(
        id="relation_cross_domain", from_entity_id=first.id, to_entity_id=other_entity.id,
        relation_type="related_to", domain_id="dom_synthetic_a", evidence_event_ids=(event.id,),
    )
    with pytest.raises(ValueError, match="cruzar domínios"):
        store.save_relation(cross_domain_relation)
    cross_domain_evidence = relation.model_copy(update={"id": "relation_cross_evidence", "evidence_event_ids": (other_event.id,)})
    with pytest.raises(ValueError, match="outro domínio"):
        store.save_relation(cross_domain_evidence)
