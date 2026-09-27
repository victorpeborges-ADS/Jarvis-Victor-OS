import sqlite3
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
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
from memory_store import (
    DatabaseCorruptError,
    EventIdentityConflict,
    MigrationError,
    MIGRATIONS_DIR,
    SQLiteMemoryStore,
    REPOSITORY_ROOT,
    _normalize_schema_sql,
    default_database_path,
)
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
    event_id: str = "real_evt_synthetic_event_a",
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
            ("0001_initial",), ("0002_audit_and_relation_domain",),
            ("0003_event_identity_and_provenance",),
            ("0004_calendar_sync_state",),
            ("0005_calendar_full_sync_reconciliation",),
            ("0006_missions",),
            ("0007_import_idempotency_result",),
            ("0008_mission_executions",),
            ("0009_artifact_reviews",),
            ("0010_review_snapshots",),
            ("0011_knowledge_decisions",),
            ("0012_selected_synthetic_sources",),
            ("0013_mission_idempotency_scopes",),
            ("0014_curated_source_admission",),
        ]
        for table in ("sources", "events", "event_provenance", "entities", "relations", "relation_evidence", "audit_entries", "calendar_sync_states", "calendar_sync_seen_events", "missions", "mission_events", "mission_idempotency", "mission_knowledge", "mission_artifact_reviews", "mission_review_decisions", "selected_synthetic_sources"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_default_database_path_is_outside_repository_and_repo_path_is_rejected(tmp_path):
    assert REPOSITORY_ROOT not in default_database_path().parents
    with pytest.raises(ValueError, match="fora do repositório"):
        SQLiteMemoryStore(REPOSITORY_ROOT / "should-never-exist.sqlite3")


def test_database_from_previous_migration_version_upgrades_without_replaying_ddl(tmp_path):
    previous_migrations = tmp_path / "previous_migrations"
    previous_migrations.mkdir()
    copyfile(MIGRATIONS_DIR / "0001_initial.sql", previous_migrations / "0001_initial.sql")
    copyfile(MIGRATIONS_DIR / "0002_audit_and_relation_domain.sql", previous_migrations / "0002_audit_and_relation_domain.sql")
    database_path = tmp_path / "private" / "memory.sqlite3"
    SQLiteMemoryStore(database_path, migrations_dir=previous_migrations).initialize()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [
            ("0001_initial",), ("0002_audit_and_relation_domain",),
        ]
        assert connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0] == 0

    SQLiteMemoryStore(database_path).initialize()
    with sqlite3.connect(database_path) as connection:
        versions = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(relations)")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert versions == [
        ("0001_initial",), ("0002_audit_and_relation_domain",),
        ("0003_event_identity_and_provenance",),
        ("0004_calendar_sync_state",),
        ("0005_calendar_full_sync_reconciliation",),
        ("0006_missions",),
        ("0007_import_idempotency_result",),
        ("0008_mission_executions",),
            ("0009_artifact_reviews",),
            ("0010_review_snapshots",),
            ("0011_knowledge_decisions",),
            ("0012_selected_synthetic_sources",),
            ("0013_mission_idempotency_scopes",),
            ("0014_curated_source_admission",),
    ]
    assert "domain_id" in columns
    assert "audit_entries" in tables


def test_unscoped_mission_idempotency_rows_are_preserved_as_unresolved_legacy(tmp_path):
    previous_migrations = tmp_path / "pre-scoped-migrations"
    previous_migrations.mkdir()
    for migration in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if migration.stem == "0013_mission_idempotency_scopes":
            continue
        copyfile(migration, previous_migrations / migration.name)

    database_path = tmp_path / "legacy" / "memory.sqlite3"
    SQLiteMemoryStore(database_path, migrations_dir=previous_migrations).initialize()
    legacy_row = (
        "owner",
        "legacy-shared-key-r2",
        "mission_legacy_record_001",
        "a" * 64,
        '{"dataset":"api_synthetic","legacy":true}',
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO mission_idempotency(owner, idempotency_key, mission_id, body_sha256, result_json) "
            "VALUES (?, ?, ?, ?, ?)",
            legacy_row,
        )

    SQLiteMemoryStore(database_path).initialize()
    with sqlite3.connect(database_path) as connection:
        migrated = connection.execute(
            "SELECT operation, owner, idempotency_key, mission_id, body_sha256, result_json "
            "FROM mission_idempotency WHERE owner=? AND idempotency_key=?",
            (legacy_row[0], legacy_row[1]),
        ).fetchone()
        assert migrated == ("legacy_unresolved", *legacy_row)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None


@pytest.mark.parametrize("applied_count", [1, 2, 3, 4])
def test_each_previous_schema_version_upgrades_to_calendar_reconciliation(tmp_path, applied_count):
    previous_migrations = tmp_path / f"previous-{applied_count}"
    previous_migrations.mkdir()
    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    for migration in migration_files[:applied_count]:
        copyfile(migration, previous_migrations / migration.name)

    database_path = tmp_path / f"from-{applied_count}" / "memory.sqlite3"
    SQLiteMemoryStore(database_path, migrations_dir=previous_migrations).initialize()
    store = SQLiteMemoryStore(database_path)
    store.initialize()
    store.initialize()
    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        seen_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calendar_sync_seen_events'"
        ).fetchone()
    assert [row[0] for row in versions] == [migration.stem for migration in migration_files]
    assert seen_table is not None


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
    first = make_event(source_id=source.id, event_id="real_evt_synthetic_event_first")
    store.save_event(first)
    duplicate = make_event(source_id=source.id, event_id="real_evt_synthetic_event_duplicate")
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
    event_a = store.save_event(make_event(source_id=source.id, event_id="real_evt_synthetic_event_a", domain_id="dom_synthetic_a"))
    event_b = store.save_event(make_event(source_id=source.id, event_id="real_evt_synthetic_event_b", domain_id="dom_synthetic_b", external_ref="synthetic-ref-b"))
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

    other_event = store.save_event(make_event(source_id=source.id, event_id="real_evt_synthetic_event_b", domain_id="dom_synthetic_b", external_ref="synthetic-ref-b"))
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


def test_event_id_namespace_rejects_demo_fixture_ids():
    with pytest.raises(ValidationError):
        make_event(event_id="evt_001")
    with pytest.raises(ValidationError):
        make_event(event_id="real_evt_bad/id")


def test_sqlite_rejects_fixture_id_even_if_model_validation_is_bypassed(tmp_path):
    store = initialized_store(tmp_path)
    source = make_source()
    store.save_source(source)
    with sqlite3.connect(store.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO events(id, source_id, event_type, title, sensitivity, payload_json, dataset, created_at) "
            "VALUES (?, ?, 'note', 'synthetic', 'normal', '{}', 'real', ?)",
            ("evt_001", source.id, now().isoformat()),
        )


def test_initialize_rejects_missing_audit_table_without_rebuilding_it(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE audit_entries")
        connection.commit()

    with pytest.raises(DatabaseCorruptError, match="diverge"):
        SQLiteMemoryStore(store.path).initialize()
    with sqlite3.connect(store.path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "audit_entries" not in names


def test_initialize_rejects_missing_required_index(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP INDEX idx_audit_entries_occurred_at")
        connection.commit()
    with pytest.raises(DatabaseCorruptError, match="diverge"):
        SQLiteMemoryStore(store.path).initialize()


def test_initialize_rejects_incompatible_column_type(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE audit_entries")
        connection.execute(
            "CREATE TABLE audit_entries (id TEXT PRIMARY KEY, operation TEXT NOT NULL, "
            "outcome TEXT NOT NULL, record_count TEXT NOT NULL DEFAULT '0', "
            "dataset TEXT NOT NULL DEFAULT 'real', occurred_at TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX idx_audit_entries_occurred_at ON audit_entries(occurred_at)")
        connection.commit()
    with pytest.raises(DatabaseCorruptError, match="diverge"):
        SQLiteMemoryStore(store.path).initialize()


def test_schema_ddl_tokenizer_normalizes_only_safe_cosmetic_changes():
    canonical = "CREATE TABLE t (id TEXT CHECK (id = 'it''s /* literal */ CHECK'))"
    cosmetic = " create /* harmless */ table t ( id text check ( id = 'it''s /* literal */ CHECK' ) ) -- tail\n"
    assert _normalize_schema_sql(canonical) == _normalize_schema_sql(cosmetic)
    assert _normalize_schema_sql(canonical) != _normalize_schema_sql(
        canonical.replace("it''s /* literal */ CHECK", "it''s /* literal */ check")
    )
    for quoted_identifier in ('"MixedName"', '"Mixed""Name"', '`Mixed``Name`', "[MixedName]"):
        assert _normalize_schema_sql(f"CREATE TABLE {quoted_identifier} (id TEXT)") == _normalize_schema_sql(
            f"create /* cosmetic */ table {quoted_identifier} ( id text )"
        )
        altered_identifier = quoted_identifier.replace("Mixed", "mixed", 1)
        assert _normalize_schema_sql(f"CREATE TABLE {quoted_identifier} (id TEXT)") != _normalize_schema_sql(
            f"CREATE TABLE {altered_identifier} (id TEXT)"
        )
    assert _normalize_schema_sql("CREATE TABLE t (id TEXT DEFAULT 'unterminated)") is None
    assert _normalize_schema_sql("CREATE TABLE t (id TEXT) /* unterminated") is None


def test_initialize_rejects_case_changed_check_literals_and_does_not_repair(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        original = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_entries'"
        ).fetchone()[0]
        altered = original.replace("'source_write'", "'SOURCE_WRITE'").replace("'success'", "'SUCCESS'")
        assert altered != original
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute("UPDATE sqlite_master SET sql=? WHERE name='audit_entries'", (altered,))
        schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version={schema_version + 1}")

    with pytest.raises(DatabaseCorruptError) as exc_info:
        SQLiteMemoryStore(store.path).initialize()
    assert str(exc_info.value) == "estrutura do banco local diverge das migrações aplicadas"
    assert str(store.path) not in str(exc_info.value)
    with sqlite3.connect(store.path) as connection:
        stored = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_entries'"
        ).fetchone()[0]
    assert stored == altered


def test_initialize_rejects_removed_check_constraint(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE audit_entries")
        connection.execute(
            "CREATE TABLE audit_entries (id TEXT PRIMARY KEY, operation TEXT NOT NULL, "
            "outcome TEXT NOT NULL, record_count INTEGER NOT NULL DEFAULT 0, "
            "dataset TEXT NOT NULL DEFAULT 'real', occurred_at TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX idx_audit_entries_occurred_at ON audit_entries(occurred_at)")
        connection.commit()
    with pytest.raises(DatabaseCorruptError, match="diverge"):
        SQLiteMemoryStore(store.path).initialize()


def test_initialize_rejects_required_index_with_wrong_definition(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP INDEX idx_audit_entries_occurred_at")
        connection.execute("CREATE INDEX idx_audit_entries_occurred_at ON audit_entries(id)")
        connection.commit()
    with pytest.raises(DatabaseCorruptError, match="diverge"):
        SQLiteMemoryStore(store.path).initialize()


def test_initialize_rejects_missing_required_column(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE audit_entries")
        connection.execute(
            "CREATE TABLE audit_entries (id TEXT PRIMARY KEY, operation TEXT NOT NULL "
            "CHECK (operation IN ('source_write', 'event_write', 'entity_write', 'relation_write', 'memory_read')), "
            "outcome TEXT NOT NULL CHECK (outcome = 'success'), dataset TEXT NOT NULL DEFAULT 'real' "
            "CHECK (dataset = 'real'), occurred_at TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX idx_audit_entries_occurred_at ON audit_entries(occurred_at)")
        connection.commit()
    with pytest.raises(DatabaseCorruptError, match="diverge"):
        SQLiteMemoryStore(store.path).initialize()


def test_record_audit_works_after_valid_schema_initialization(tmp_path):
    store = initialized_store(tmp_path)
    store.record_audit("memory_read", 0)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT operation, outcome, record_count FROM audit_entries"
        ).fetchall() == [("memory_read", "success", 0)]


def test_initialize_accepts_safe_cosmetic_ddl_and_record_audit_still_works(tmp_path):
    store = initialized_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        original = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_entries'"
        ).fetchone()[0]
        cosmetic = original.replace(
            "CREATE TABLE audit_entries", "create  table /* cosmetic */ audit_entries", 1
        ).replace("record_count INTEGER", "record_count    integer", 1)
        assert cosmetic != original
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute("UPDATE sqlite_master SET sql=? WHERE name='audit_entries'", (cosmetic,))
        schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version={schema_version + 1}")

    reopened = SQLiteMemoryStore(store.path)
    reopened.initialize()
    reopened.record_audit("memory_read", 0)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT operation, outcome FROM audit_entries").fetchall() == [
            ("memory_read", "success")
        ]


def test_internal_id_collision_from_another_source_is_rejected_without_mutation(tmp_path):
    store = initialized_store(tmp_path)
    source_a = make_source("src_calendar_a")
    source_b = make_source("src_calendar_b")
    store.save_source(source_a)
    store.save_source(source_b)
    first = make_event(
        source_id=source_a.id, event_id="real_evt_shared_001", domain_id="dom_synthetic_a",
        external_ref="external-a",
    )
    store.save_event(first)
    with sqlite3.connect(store.path) as connection:
        before_audit = connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]

    conflicting = make_event(
        source_id=source_b.id, event_id="real_evt_shared_001", domain_id="dom_synthetic_b",
        external_ref="external-b",
    ).model_copy(update={"title": "Ataque de substituição"})
    with pytest.raises(EventIdentityConflict, match="outra identidade"):
        store.save_event(conflicting)

    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT source_id, title, domain_id FROM events WHERE id=?", (first.id,)
        ).fetchone()
        provenance = connection.execute(
            "SELECT source_id, external_ref FROM event_provenance WHERE event_id=?", (first.id,)
        ).fetchone()
        after_audit = connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]
    assert row == (source_a.id, first.title, "dom_synthetic_a")
    assert provenance == (source_a.id, "external-a")
    assert after_audit == before_audit
    assert [item.event.id for item in store.list_authorized_events(scope("dom_synthetic_a"))] == [first.id]
    assert store.list_authorized_events(scope("dom_synthetic_b")) == []


def test_sqlite_triggers_keep_event_and_provenance_identity_immutable(tmp_path):
    store = initialized_store(tmp_path)
    source_a = make_source("src_calendar_a")
    source_b = make_source("src_calendar_b")
    store.save_source(source_a)
    store.save_source(source_b)
    event = store.save_event(make_event(source_id=source_a.id, event_id="real_evt_immutable_01"))
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE events SET source_id=? WHERE id=?", (source_b.id, event.id))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE event_provenance SET external_ref='different-reference' WHERE event_id=?",
                (event.id,),
            )


def test_failed_audit_write_rolls_back_event_and_provenance(tmp_path):
    store = initialized_store(tmp_path)
    source = make_source()
    store.save_source(source)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_event_audit BEFORE INSERT ON audit_entries "
            "WHEN NEW.operation='event_write' BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
        connection.commit()
    event = make_event(source_id=source.id)
    with pytest.raises(sqlite3.IntegrityError):
        store.save_event(event)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events WHERE id=?", (event.id,)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM event_provenance WHERE event_id=?", (event.id,)).fetchone()[0] == 0


def test_concurrent_same_external_identity_remains_idempotent(tmp_path):
    store = initialized_store(tmp_path)
    source = make_source()
    store.save_source(source)
    events = [
        make_event(
            source_id=source.id,
            event_id=f"real_evt_concurrent_{index}",
            external_ref="external-concurrent-singleton",
        )
        for index in range(8)
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        saved = list(executor.map(store.save_event, events))
    assert len({event.id for event in saved}) == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE source_id=?", (source.id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM event_provenance WHERE source_id=? AND external_ref=?",
            (source.id, "external-concurrent-singleton"),
        ).fetchone()[0] == 1
