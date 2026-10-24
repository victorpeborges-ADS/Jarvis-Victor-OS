"""Categorias de memória separadas da captura explícita.

A captura explícita continua em local_captures. Este módulo guarda só fato
confirmado, evidência de fonte sintética e proposta inferida. Uma resposta
do assistente não entra como fato do proprietário.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import datetime, timezone

from memory_store import SQLiteMemoryStore

DOMAINS = (
    "dom_synthetic_a",
    "dom_synthetic_b",
    "dom_synthetic_c",
    "dom_synthetic_d",
    "dom_synthetic_e",
    "dom_synthetic_f",
    "dom_synthetic_g",
    "dom_synthetic_h",
)
CATEGORIES = {
    "confirmed_fact": ("confirmed_facts", "owner_confirmation"),
    "external_evidence": ("external_evidence", "synthetic_source"),
    "inferred_proposal": ("inferred_proposals", "assistant_inference"),
}
MAX_TEXT_CHARS = 80
_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,80}\Z")
_REF = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def _category(category: str) -> tuple[str, str]:
    found = CATEGORIES.get(category)
    if found is None:
        raise ValueError("memória recusada")
    return found


def _domain(domain_id: str) -> str:
    if domain_id not in DOMAINS:
        raise ValueError("memória recusada")
    return domain_id


def _body(body: str) -> str:
    if not isinstance(body, str) or _TEXT.fullmatch(body) is None or len(body) > MAX_TEXT_CHARS:
        raise ValueError("memória recusada")
    return body


def _ref(source_ref: str) -> str:
    if not isinstance(source_ref, str) or _REF.fullmatch(source_ref) is None:
        raise ValueError("memória recusada")
    return source_ref


def _moment(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("memória recusada")
    return now.astimezone(timezone.utc).isoformat()


def _row(category: str, row) -> dict[str, str | int]:
    return {
        "id": row[0],
        "category": category,
        "domain_id": row[1],
        "body": row[2],
        "source_kind": row[3],
        "source_ref": row[4],
        "version": row[5],
        "recorded_at": row[6],
        "revised_at": row[7],
    }


def record_memory(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    category: str,
    body: str,
    source_kind: str,
    source_ref: str,
    now: datetime,
) -> dict[str, str | int]:
    if owner != "owner" or source_kind == "assistant_reply":
        raise ValueError("memória recusada")
    table, expected_kind = _category(category)
    if source_kind != expected_kind:
        raise ValueError("memória recusada")
    domain = _domain(domain_id)
    text = _body(body)
    origin = _ref(source_ref)
    recorded_at = _moment(now)
    record_id = secrets.token_hex(16)
    try:
        with store.transaction() as connection:
            connection.execute(
                f"""INSERT INTO {table}(
                        id, owner, domain_id, body, source_kind, source_ref,
                        version, recorded_at, revised_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (record_id, owner, domain, text, expected_kind, origin, recorded_at, recorded_at),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("memória recusada") from exc
    return {
        "id": record_id,
        "category": category,
        "domain_id": domain,
        "body": text,
        "source_kind": expected_kind,
        "source_ref": origin,
        "version": 1,
        "recorded_at": recorded_at,
        "revised_at": recorded_at,
    }


def revise_memory(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    category: str,
    record_id: str,
    body: str,
    now: datetime,
    expected_revision: int | None = None,
) -> dict[str, str | int]:
    if owner != "owner" or not isinstance(record_id, str) or len(record_id) != 32:
        raise ValueError("memória recusada")
    table, _expected_kind = _category(category)
    domain = _domain(domain_id)
    text = _body(body)
    revised_at = _moment(now)
    try:
        with store.transaction() as connection:
            row = connection.execute(
                f"""SELECT version, source_kind, source_ref, recorded_at
                    FROM {table}
                    WHERE id = ? AND owner = ? AND domain_id = ?""",
                (record_id, owner, domain),
            ).fetchone()
            if row is None:
                raise ValueError("memória recusada")
            if expected_revision is not None and row[0] != expected_revision:
                from memory_deletions import MemoryRevisionConflict
                raise MemoryRevisionConflict("revisão desatualizada")
            connection.execute(
                f"""UPDATE {table}
                    SET body = ?, version = ?, revised_at = ?
                    WHERE id = ? AND owner = ? AND domain_id = ?""",
                (text, row[0] + 1, revised_at, record_id, owner, domain),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("memória recusada") from exc
    return {
        "id": record_id,
        "category": category,
        "domain_id": domain,
        "body": text,
        "source_kind": row[1],
        "source_ref": row[2],
        "version": row[0] + 1,
        "recorded_at": row[3],
        "revised_at": revised_at,
    }


def delete_memory(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    category: str,
    record_id: str,
    expected_revision: int | None = None,
) -> dict[str, str | bool]:
    """Purge current row and persist a content-free replay record atomically."""
    if owner != "owner" or not isinstance(record_id, str):
        raise ValueError("memória recusada")
    table, _expected_kind = _category(category)
    domain = _domain(domain_id)
    with store.transaction() as connection:
        row = connection.execute(
            f"SELECT version, body FROM {table} WHERE id = ? AND owner = ? AND domain_id = ?",
            (record_id, owner, domain),
        ).fetchone()
        if row is None:
            from memory_deletions import repeat_deletion
            repeated = repeat_deletion(
                connection, category=category, domain_id=domain, record_id=record_id,
                expected_revision=expected_revision,
            )
            if repeated is not None:
                return {
                    "id": record_id, "category": category, "domain_id": domain,
                    "deleted_revision": repeated["deleted_revision"],
                    "operation_id": repeated["operation_id"],
                    "removed_from_open_database": True,
                    "historical_backup_may_keep_text": True,
                    "idempotent": True,
                }
            raise ValueError("memória recusada")
        if expected_revision is not None and row[0] != expected_revision:
            from memory_deletions import MemoryRevisionConflict
            raise MemoryRevisionConflict("revisão desatualizada")
        from memory_deletions import write_tombstone
        tombstone = write_tombstone(
            connection, category=category, domain_id=domain, record_id=record_id,
            revision=row[0], body=row[1], deleted_at=datetime.now(timezone.utc),
        )
        deleted = connection.execute(
            f"DELETE FROM {table} WHERE id = ? AND owner = ? AND domain_id = ?",
            (record_id, owner, domain),
        ).rowcount
    if deleted != 1:
        raise ValueError("memória recusada")
    return {
        "id": record_id,
        "category": category,
        "domain_id": domain,
        "deleted_revision": row[0],
        "operation_id": tombstone["operation_id"],
        "removed_from_open_database": True,
        "historical_backup_may_keep_text": True,
    }


def read_memory(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    category: str,
    record_id: str,
) -> dict[str, str | int]:
    if owner != "owner" or not isinstance(record_id, str):
        raise ValueError("memória recusada")
    table, _expected_kind = _category(category)
    domain = _domain(domain_id)
    with store.transaction() as connection:
        row = connection.execute(
            f"""SELECT id, domain_id, body, source_kind, source_ref,
                       version, recorded_at, revised_at
                FROM {table}
                WHERE id = ? AND owner = ? AND domain_id = ?""",
            (record_id, owner, domain),
        ).fetchone()
    if row is None:
        raise ValueError("memória recusada")
    return _row(category, row)


def list_memory(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    category: str,
) -> list[dict[str, str | int]]:
    if owner != "owner":
        raise ValueError("memória recusada")
    table, _expected_kind = _category(category)
    domain = _domain(domain_id)
    with store.transaction() as connection:
        rows = connection.execute(
            f"""SELECT id, domain_id, body, source_kind, source_ref,
                       version, recorded_at, revised_at
                FROM {table}
                WHERE owner = ? AND domain_id = ?
                ORDER BY recorded_at, id""",
            (owner, domain),
        ).fetchall()
    return [_row(category, row) for row in rows]


def page_memory(
    store: SQLiteMemoryStore, owner: str, domain_id: str, category: str, offset: int,
) -> dict[str, str | int] | None:
    if owner != "owner" or not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 5000:
        raise ValueError("memória recusada")
    domain = _domain(domain_id)
    if category == "explicit_capture":
        if domain != "dom_synthetic_a":
            raise ValueError("memória recusada")
        with store.transaction() as connection:
            row = connection.execute(
                """SELECT id, domain_id, body, created_at, version, revised_at
                   FROM local_captures WHERE owner = ? AND domain_id = ?
                   ORDER BY created_at, id LIMIT 1 OFFSET ?""",
                (owner, domain, offset),
            ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "category": category, "domain_id": row[1], "body": row[2],
                "source_kind": "user_authored_capture", "source_ref": "explicit_capture",
                "version": row[4], "recorded_at": row[3], "revised_at": row[5] or row[3]}
    table, _ = _category(category)
    with store.transaction() as connection:
        row = connection.execute(
            f"""SELECT id, domain_id, body, source_kind, source_ref, version, recorded_at, revised_at
                FROM {table} WHERE owner = ? AND domain_id = ?
                ORDER BY recorded_at, id LIMIT 1 OFFSET ?""",
            (owner, domain, offset),
        ).fetchone()
    return None if row is None else _row(category, row)
