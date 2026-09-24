"""SQLite persistence for the real dataset, kept outside the source tree."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import secrets
import sqlite3
import stat
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from pydantic import BaseModel, ValidationError

from domain_registry import CANONICAL_CONNECTORS, CANONICAL_DOMAIN_IDS, CANONICAL_RESOURCES
from memory_models import AuditRecord, EntityRecord, EventRecord, ReadScope, RelationRecord, SourceRecord, StrictRecord

logger = logging.getLogger(__name__)
API_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = API_ROOT.parents[1]
MIGRATIONS_DIR = API_ROOT / "migrations"

_SCHEMA_SQL_KEYWORDS = frozenset({
    "ABORT", "ADD", "ALTER", "AND", "BEFORE", "BEGIN", "BETWEEN", "CASCADE", "CHECK",
    "COLUMN", "CREATE", "DEFAULT", "DELETE", "END", "GLOB", "IN", "INDEX", "INSERT",
    "INTEGER", "INTO", "IS", "KEY", "NOT", "NULL", "OF", "ON", "OR", "PRIMARY",
    "RAISE", "REAL", "REFERENCES", "SELECT", "TABLE", "TEXT", "THEN", "TRIGGER", "UNIQUE",
    "UPDATE", "WHEN",
})
_SCHEMA_SQL_OPERATORS = ("->>", "->", "||", "<<", ">>", "<=", ">=", "==", "!=", "<>")


def _normalize_schema_sql(sql: str) -> tuple[tuple[str, str], ...] | None:
    """Tokenize migration DDL while preserving literals and quoted identifiers.

    Only SQL keyword casing, comments, and whitespace between tokens are
    normalized. Unknown or malformed quoting returns None so callers compare
    the original SQL byte-for-byte instead of guessing at its meaning.
    """
    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char in " \t\r\n\f\v":
            index += 1
            continue
        if char == "-" and sql[index:index + 2] == "--":
            newline = sql.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if char == "/" and sql[index:index + 2] == "/*":
            end = sql.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
            continue
        if char == "\x00":
            return None

        if char in "'\"`[":
            closing = "]" if char == "[" else char
            cursor = index + 1
            closed = False
            while cursor < length:
                if sql[cursor] == closing:
                    if char != "[" and cursor + 1 < length and sql[cursor + 1] == closing:
                        cursor += 2
                        continue
                    cursor += 1
                    closed = True
                    break
                cursor += 1
            if not closed:
                return None
            kind = "string-literal" if char == "'" else "quoted-identifier"
            tokens.append((kind, sql[index:cursor]))
            index = cursor
            continue

        if (
            char == "_" or char == "$" or (char.isascii() and char.isalpha()) or ord(char) >= 0x80
        ):
            cursor = index + 1
            while cursor < length:
                candidate = sql[cursor]
                if (
                    candidate == "_" or candidate == "$"
                    or (candidate.isascii() and candidate.isalnum()) or ord(candidate) >= 0x80
                ):
                    cursor += 1
                else:
                    break
            word = sql[index:cursor]
            if word.isascii() and word.upper() in _SCHEMA_SQL_KEYWORDS:
                tokens.append(("keyword", word.upper()))
            else:
                tokens.append(("identifier", word))
            index = cursor
            continue

        if (
            (char.isascii() and char.isdigit())
            or (char == "." and index + 1 < length and sql[index + 1].isascii() and sql[index + 1].isdigit())
        ):
            cursor = index
            if sql[index:index + 2].lower() == "0x":
                cursor += 2
                digits_start = cursor
                while (
                    cursor < length and sql[cursor].isascii()
                    and sql[cursor].lower() in "0123456789abcdef"
                ):
                    cursor += 1
                if cursor == digits_start:
                    return None
            else:
                while cursor < length and sql[cursor].isascii() and sql[cursor].isdigit():
                    cursor += 1
                if cursor < length and sql[cursor] == ".":
                    cursor += 1
                    while cursor < length and sql[cursor].isascii() and sql[cursor].isdigit():
                        cursor += 1
                if cursor < length and sql[cursor] in "eE":
                    exponent = cursor + 1
                    if exponent < length and sql[exponent] in "+-":
                        exponent += 1
                    digits_start = exponent
                    while exponent < length and sql[exponent].isascii() and sql[exponent].isdigit():
                        exponent += 1
                    if exponent == digits_start:
                        return None
                    cursor = exponent
            tokens.append(("number-literal", sql[index:cursor]))
            index = cursor
            continue

        operator = next((candidate for candidate in _SCHEMA_SQL_OPERATORS if sql.startswith(candidate, index)), None)
        if operator is not None:
            tokens.append(("operator", operator))
            index += len(operator)
            continue
        tokens.append(("symbol", char))
        index += 1
    return tuple(tokens)


class MemoryStoreError(RuntimeError):
    """A storage error safe to report without including record contents."""


class MigrationError(MemoryStoreError):
    pass


class DatabaseCorruptError(MemoryStoreError):
    pass


class EventIdentityConflict(ValueError):
    """An internal event ID or source reference was reused for another event."""


class StoredEvent(StrictRecord):
    source: SourceRecord
    event: EventRecord


def default_database_path() -> Path:
    """Return the platform data path; no repository-relative fallback exists."""
    override = os.environ.get("JARVIS_DATABASE_PATH")
    if override:
        return _safe_database_path(Path(override))
    if platform.system() == "Darwin":
        path = Path.home() / "Library" / "Application Support" / "JARVIS" / "memory.sqlite3"
    else:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = data_home / "JARVIS" / "memory.sqlite3"
    return _safe_database_path(path)


def _safe_database_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("o arquivo do banco não pode ser link simbólico")
    resolved = expanded.parent.resolve() / expanded.name
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return resolved
    raise ValueError("o banco local deve ficar fora do repositório")


def _aware_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validated(model_type: type[BaseModel], value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    return model_type.model_validate(value)


class SQLiteMemoryStore:
    """Small repository with transactional writes and grant-scoped read methods."""

    def __init__(self, path: Path | str | None = None, *, migrations_dir: Path | None = None) -> None:
        self.path = _safe_database_path(Path(path)) if path is not None else default_database_path()
        self.migrations_dir = migrations_dir or MIGRATIONS_DIR
        self._initialized = False

    def initialize(self) -> None:
        self._prepare_private_path()
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise MemoryStoreError("não foi possível habilitar WAL")
            connection.execute("PRAGMA synchronous=FULL")
            self._apply_migrations(connection)
            self._validate_schema(connection)
            check = connection.execute("PRAGMA quick_check").fetchone()[0]
            if check != "ok":
                raise DatabaseCorruptError("banco local corrompido")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise DatabaseCorruptError("integridade referencial do banco inválida")
        except sqlite3.DatabaseError as exc:
            raise DatabaseCorruptError("não foi possível abrir o banco local") from exc
        finally:
            if connection is not None:
                connection.close()
        self._initialized = True

    def _prepare_private_path(self) -> None:
        if self.path.is_symlink():
            raise ValueError("o arquivo do banco não pode ser link simbólico")
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = self.path.parent.stat()
        if directory_stat.st_uid != os.getuid():
            raise PermissionError("diretório do banco pertence a outro usuário")
        if parent_existed and stat.S_IMODE(directory_stat.st_mode) & 0o077:
            raise PermissionError("diretório do banco precisa de permissões privadas")
        if not parent_existed:
            os.chmod(self.path.parent, 0o700)
        if self.path.exists():
            file_stat = self.path.stat()
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("o caminho do banco precisa ser um arquivo regular")
            if file_stat.st_uid != os.getuid():
                raise PermissionError("arquivo do banco pertence a outro usuário")
            os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        if self.path.exists():
            os.chmod(self.path, 0o600)
        return connection

    def _apply_migrations(self, connection: sqlite3.Connection) -> None:
        files = sorted(self.migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        if not files:
            raise MigrationError("nenhuma migração local disponível")
        known_versions = {file.stem for file in files}
        if self.migrations_dir.resolve() == MIGRATIONS_DIR.resolve() and (
            "0003_event_identity_and_provenance" not in known_versions
        ):
            raise MigrationError("migração estrutural obrigatória indisponível")
        existing_tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if "schema_migrations" not in existing_tables and existing_tables:
            raise DatabaseCorruptError("estrutura do banco local sem histórico de migrações")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {
            row["version"]: row["checksum"]
            for row in connection.execute("SELECT version, checksum FROM schema_migrations")
        }
        if set(applied) - known_versions:
            raise MigrationError("o banco contém migração sem arquivo correspondente")

        for migration in files:
            version = migration.stem
            sql = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise MigrationError("checksum de migração aplicada foi alterado")
                continue
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._execute_sql_transactionally(connection, sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
                    (version, checksum, datetime.now(timezone.utc).isoformat()),
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                if isinstance(exc, sqlite3.DatabaseError):
                    raise MigrationError("migração local falhou e foi revertida") from exc
                raise

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        """Compare the effective database with a fresh schema built from its migrations."""
        migration_files = sorted(self.migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        if not migration_files:
            raise MigrationError("nenhuma migração local disponível")
        applied = [
            row[0] for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        expected_versions = [migration.stem for migration in migration_files]
        if applied != expected_versions:
            raise DatabaseCorruptError("histórico de migrações do banco local inconsistente")
        expected = sqlite3.connect(":memory:")
        try:
            expected.execute(
                "CREATE TABLE schema_migrations ("
                "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            for migration in migration_files:
                self._execute_sql_transactionally(
                    expected, migration.read_text(encoding="utf-8")
                )
            differences = self._schema_differences(connection, expected)
        except sqlite3.DatabaseError as exc:
            raise MigrationError("não foi possível validar o esquema esperado") from exc
        finally:
            expected.close()
        if differences:
            logger.error("SQLite schema validation failed: %s", ", ".join(differences))
            raise DatabaseCorruptError("estrutura do banco local diverge das migrações aplicadas")

    @staticmethod
    def _schema_differences(actual: sqlite3.Connection, expected: sqlite3.Connection) -> list[str]:
        differences: list[str] = []

        def objects(connection: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, object]]:
            rows = connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )
            result: dict[tuple[str, str], tuple[str, object]] = {}
            for row in rows:
                sql = row[3]
                normalized = _normalize_schema_sql(sql) if sql is not None else None
                # If tokenization is uncertain, exact SQL is the only safe comparison.
                signature: object = ("tokens", normalized) if normalized is not None else ("raw", sql)
                result[(row[0], row[1])] = (row[2], signature)
            return result

        actual_objects = objects(actual)
        expected_objects = objects(expected)
        if actual_objects != expected_objects:
            differences.append("objects")

        tables = {
            name for kind, name in expected_objects if kind == "table"
        } | {name for kind, name in actual_objects if kind == "table"}

        def identifier(value: str) -> str:
            return '"' + value.replace('"', '""') + '"'

        for table in sorted(tables):
            quoted = identifier(table)
            for pragma in ("table_xinfo",):
                actual_rows = actual.execute(f"PRAGMA {pragma}({quoted})").fetchall()
                expected_rows = expected.execute(f"PRAGMA {pragma}({quoted})").fetchall()
                actual_signature = [
                    (row[1], (row[2] or "").upper(), row[3], row[4], row[5], row[6])
                    for row in actual_rows
                ]
                expected_signature = [
                    (row[1], (row[2] or "").upper(), row[3], row[4], row[5], row[6])
                    for row in expected_rows
                ]
                if actual_signature != expected_signature:
                    differences.append(f"columns:{table}")

            def indexes(connection: sqlite3.Connection) -> dict[str, tuple]:
                result: dict[str, tuple] = {}
                for row in connection.execute(f"PRAGMA index_list({quoted})"):
                    name = row[1]
                    index_rows = connection.execute(
                        f"PRAGMA index_xinfo({identifier(name)})"
                    ).fetchall()
                    result[name] = (
                        row[2], row[3], row[4],
                        tuple((entry[0], entry[1], entry[2], entry[3], entry[4], entry[5]) for entry in index_rows),
                    )
                return result

            if indexes(actual) != indexes(expected):
                differences.append(f"indexes:{table}")

            def foreign_keys(connection: sqlite3.Connection) -> tuple:
                return tuple(sorted(
                    (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
                    for row in connection.execute(f"PRAGMA foreign_key_list({quoted})")
                ))

            if foreign_keys(actual) != foreign_keys(expected):
                differences.append(f"foreign-keys:{table}")
        return differences

    @staticmethod
    def _execute_sql_transactionally(connection: sqlite3.Connection, sql: str) -> None:
        pending = ""
        for line in sql.splitlines(keepends=True):
            pending += line
            if sqlite3.complete_statement(pending):
                statement = pending.strip()
                if statement:
                    connection.execute(statement)
                pending = ""
        if pending.strip():
            raise MigrationError("migração contém uma instrução SQL incompleta")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise MemoryStoreError("banco local ainda não foi inicializado")

    @staticmethod
    def _insert_audit(connection: sqlite3.Connection, operation: str, record_count: int = 0) -> None:
        entry = AuditRecord(operation=operation, record_count=record_count)
        connection.execute(
            "INSERT INTO audit_entries(id, operation, outcome, record_count, dataset, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
            (secrets.token_hex(16), entry.operation, entry.outcome, entry.record_count,
             entry.dataset, entry.occurred_at.isoformat()),
        )

    def record_audit(self, operation: str, record_count: int = 0) -> None:
        """Persist an allow-listed operation and count, never event content or IDs."""
        self._require_initialized()
        entry = AuditRecord(operation=operation, record_count=record_count)
        with self.transaction() as connection:
            self._insert_audit(connection, entry.operation, entry.record_count)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._require_initialized()
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_source(self, source_value: SourceRecord | dict) -> SourceRecord:
        source = _validated(SourceRecord, source_value)
        scopes_json = json.dumps(list(source.scopes), ensure_ascii=False, allow_nan=False)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO sources(id, provider, resource_id, account_ref, scopes_json, sync_status, dataset, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (source.id, source.provider, source.resource_id, source.account_ref, scopes_json,
                 source.sync_status, source.dataset, source.created_at.isoformat()),
            )
            self._insert_audit(connection, "source_write")
        return source

    def save_event(self, event_value: EventRecord | dict) -> EventRecord:
        event = _validated(EventRecord, event_value)
        if len(json.dumps(event.payload_minimized, ensure_ascii=False, allow_nan=False)) > 65536:
            raise ValueError("payload minimizado excede o limite")

        provenance = event.provenance
        with self.transaction() as connection:
            source = connection.execute(
                "SELECT id, provider, resource_id, dataset FROM sources WHERE id=?", (provenance.source_id,)
            ).fetchone()
            if source is None:
                raise ValueError("origem do evento não existe")
            if source["dataset"] != "real" or source["provider"] not in CANONICAL_CONNECTORS:
                raise ValueError("origem do evento não é autorizável")
            if source["resource_id"] not in CANONICAL_RESOURCES.get(source["provider"], frozenset()):
                raise ValueError("recurso da origem não é autorizável")

            duplicate = connection.execute(
                "SELECT e.id, e.dataset, e.source_id, p.source_id AS provenance_source_id, "
                "p.external_ref, s.provider, s.resource_id, s.dataset AS source_dataset "
                "FROM events e LEFT JOIN event_provenance p ON p.event_id=e.id "
                "LEFT JOIN sources s ON s.id=e.source_id WHERE e.id=?", (event.id,)
            ).fetchone()
            by_external_ref = None
            if provenance.external_ref is not None:
                by_external_ref = connection.execute(
                    "SELECT e.id, e.dataset, e.source_id, p.source_id AS provenance_source_id, "
                    "p.external_ref, s.provider, s.resource_id, s.dataset AS source_dataset "
                    "FROM event_provenance p JOIN events e ON e.id=p.event_id "
                    "JOIN sources s ON s.id=e.source_id WHERE p.source_id=? AND p.external_ref=?",
                    (provenance.source_id, provenance.external_ref),
                ).fetchone()
            incoming_identity = (
                event.dataset, source["id"], source["provider"], source["resource_id"],
                provenance.external_ref,
            )
            if duplicate and not self._same_event_identity(duplicate, incoming_identity):
                raise EventIdentityConflict("ID interno já pertence a outra identidade de evento")
            if by_external_ref and not self._same_event_identity(by_external_ref, incoming_identity):
                raise EventIdentityConflict("referência externa já pertence a outra identidade de evento")
            if duplicate and by_external_ref and duplicate["id"] != by_external_ref["id"]:
                raise EventIdentityConflict("ID interno e referência externa apontam para eventos distintos")
            existing = duplicate or by_external_ref
            event_id = existing["id"] if existing else event.id
            values = (
                provenance.source_id, event.event_type, event.title, event.domain_id,
                event.sensitivity, _aware_iso(event.occurred_at),
                json.dumps(event.payload_minimized, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                event.dataset,
            )
            if existing:
                connection.execute(
                    "UPDATE events SET event_type=?, title=?, domain_id=?, sensitivity=?, "
                    "occurred_at=?, payload_json=?, dataset=? WHERE id=?",
                    (*values[1:], event_id),
                )
            else:
                connection.execute(
                    "INSERT INTO events(id, source_id, event_type, title, domain_id, sensitivity, occurred_at, payload_json, dataset, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (event.id, *values, event.created_at.isoformat()),
                )
            connection.execute(
                "INSERT INTO event_provenance(event_id, source_id, external_ref, observed_at, last_verified_at, valid_until, "
                "confidence, classification_method, classified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(event_id) DO UPDATE SET observed_at=excluded.observed_at, "
                "last_verified_at=excluded.last_verified_at, valid_until=excluded.valid_until, "
                "confidence=excluded.confidence, classification_method=excluded.classification_method, classified_at=excluded.classified_at",
                (event_id, provenance.source_id, provenance.external_ref, provenance.observed_at.isoformat(),
                 _aware_iso(provenance.last_verified_at), _aware_iso(provenance.valid_until), provenance.confidence,
                 provenance.classification_method, _aware_iso(provenance.classified_at)),
            )
            self._insert_audit(connection, "event_write")
        return event.model_copy(update={"id": event_id})

    @staticmethod
    def _same_event_identity(row: sqlite3.Row, incoming: tuple[str, str, str, str, str | None]) -> bool:
        existing_identity = (
            row["dataset"], row["source_id"], row["provider"], row["resource_id"], row["external_ref"],
        )
        provenance_source_id = row["provenance_source_id"]
        return provenance_source_id == row["source_id"] and existing_identity == incoming

    def save_entity(self, entity_value: EntityRecord | dict) -> EntityRecord:
        entity = _validated(EntityRecord, entity_value)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO entities(id, entity_type, name, domain_id, sensitivity, dataset, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entity.id, entity.entity_type, entity.name, entity.domain_id, entity.sensitivity,
                 entity.dataset, entity.created_at.isoformat()),
            )
            self._insert_audit(connection, "entity_write")
        return entity

    def save_relation(self, relation_value: RelationRecord | dict) -> RelationRecord:
        relation = _validated(RelationRecord, relation_value)
        with self.transaction() as connection:
            endpoint_domains = connection.execute(
                "SELECT id, domain_id FROM entities WHERE id IN (?, ?)",
                (relation.from_entity_id, relation.to_entity_id),
            ).fetchall()
            if len(endpoint_domains) != 2:
                raise sqlite3.IntegrityError("relação aponta para entidade ausente")
            if any(row["domain_id"] != relation.domain_id for row in endpoint_domains):
                raise ValueError("relação não pode cruzar domínios sem classificação comum")
            if relation.evidence_event_ids:
                placeholders = ",".join("?" for _ in relation.evidence_event_ids)
                evidence_domains = connection.execute(
                    f"SELECT id, domain_id FROM events WHERE id IN ({placeholders})",
                    relation.evidence_event_ids,
                ).fetchall()
                if len(evidence_domains) != len(set(relation.evidence_event_ids)):
                    raise sqlite3.IntegrityError("evidência da relação aponta para evento ausente")
                if any(row["domain_id"] != relation.domain_id for row in evidence_domains):
                    raise ValueError("evidência da relação pertence a outro domínio")
            connection.execute(
                "INSERT INTO relations(id, from_entity_id, to_entity_id, relation_type, domain_id, review_status, dataset, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (relation.id, relation.from_entity_id, relation.to_entity_id, relation.relation_type,
                 relation.domain_id, relation.review_status, relation.dataset, relation.created_at.isoformat()),
            )
            connection.executemany(
                "INSERT INTO relation_evidence(relation_id, event_id) VALUES (?, ?)",
                [(relation.id, event_id) for event_id in relation.evidence_event_ids],
            )
            self._insert_audit(connection, "relation_write")
        return relation

    def list_authorized_events(
        self,
        scopes: Sequence[ReadScope],
        requested_domain: str | None = None,
    ) -> list[StoredEvent]:
        self._require_initialized()
        query, parameters = self._authorized_query(scopes, requested_domain)
        with closing(self._connect()) as connection:
            rows = connection.execute(query + " ORDER BY COALESCE(e.occurred_at, e.created_at), e.id", parameters).fetchall()
        records = [record for row in rows if (record := self._row_to_record(row)) is not None]
        self.record_audit("memory_read", len(records))
        return records

    def get_authorized_event(
        self,
        event_id: str,
        scopes: Sequence[ReadScope],
        requested_domain: str | None = None,
    ) -> StoredEvent | None:
        self._require_initialized()
        query, parameters = self._authorized_query(scopes, requested_domain)
        with closing(self._connect()) as connection:
            row = connection.execute(query + " AND e.id=? LIMIT 1", (*parameters, event_id)).fetchone()
        record = self._row_to_record(row) if row is not None else None
        self.record_audit("memory_read", int(record is not None))
        return record

    @staticmethod
    def _authorized_query(scopes: Sequence[ReadScope], requested_domain: str | None) -> tuple[str, tuple]:
        validated_scopes = [ReadScope.model_validate(scope.model_dump(mode="python")) for scope in scopes]
        if not validated_scopes:
            raise PermissionError("consulta exige ao menos uma concessão")
        if requested_domain is not None and requested_domain not in CANONICAL_DOMAIN_IDS:
            raise PermissionError("domain_id de consulta desconhecido")

        predicates: list[str] = []
        parameters: list[str] = []
        for scope in validated_scopes:
            domains = sorted(scope.domain_ids)
            placeholders = ",".join("?" for _ in domains)
            predicates.append(
                f"(s.provider=? AND s.resource_id=? AND e.domain_id IN ({placeholders}))"
            )
            parameters.extend([scope.connector, scope.resource_id, *domains])
        query = (
            "SELECT e.id AS event_id, e.event_type, e.title, e.domain_id, e.sensitivity, e.occurred_at, "
            "e.payload_json, e.dataset AS event_dataset, e.created_at AS event_created_at, "
            "p.source_id AS provenance_source_id, p.external_ref, p.observed_at, p.last_verified_at, "
            "p.valid_until, p.confidence, p.classification_method, p.classified_at, "
            "s.id AS source_id, s.provider, s.resource_id, s.account_ref, s.scopes_json, "
            "s.sync_status, s.dataset AS source_dataset, s.created_at AS source_created_at "
            "FROM events e JOIN event_provenance p ON p.event_id=e.id "
            "JOIN sources s ON s.id=e.source_id "
            "WHERE e.dataset='real' AND s.dataset='real' AND e.domain_id IS NOT NULL AND ("
            + " OR ".join(predicates)
            + ")"
        )
        if requested_domain is not None:
            query += " AND e.domain_id=?"
            parameters.append(requested_domain)
        return query, tuple(parameters)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> StoredEvent | None:
        try:
            source = SourceRecord.model_validate(
                {
                    "id": row["source_id"], "provider": row["provider"], "resource_id": row["resource_id"],
                    "account_ref": row["account_ref"], "scopes": json.loads(row["scopes_json"]),
                    "sync_status": row["sync_status"], "dataset": row["source_dataset"],
                    "created_at": row["source_created_at"],
                }
            )
            provenance = {
                "source_id": row["provenance_source_id"], "external_ref": row["external_ref"],
                "observed_at": row["observed_at"], "last_verified_at": row["last_verified_at"],
                "valid_until": row["valid_until"], "confidence": row["confidence"],
                "classification_method": row["classification_method"], "classified_at": row["classified_at"],
            }
            event = EventRecord.model_validate(
                {
                    "id": row["event_id"], "event_type": row["event_type"], "title": row["title"],
                    "domain_id": row["domain_id"], "sensitivity": row["sensitivity"],
                    "occurred_at": row["occurred_at"], "payload_minimized": json.loads(row["payload_json"]),
                    "provenance": provenance, "dataset": row["event_dataset"],
                    "created_at": row["event_created_at"],
                }
            )
            if event.provenance.source_id != source.id:
                return None
            return StoredEvent(source=source, event=event)
        except (ValidationError, TypeError, ValueError, json.JSONDecodeError):
            # Do not log titles, payloads, IDs or validation input.
            logger.warning("Ignoring malformed row in local memory store")
            return None
