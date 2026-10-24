"""Durable, content-free deletion records shared by purge and restore."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

from memory_categories import CATEGORIES, DOMAINS

CATEGORY_TABLES = {"explicit_capture": "local_captures"} | {
    category: mapping[0] for category, mapping in CATEGORIES.items()
}


class MemoryRevisionConflict(ValueError):
    """A revision disagrees with a durable deletion decision."""


def content_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8", errors="strict")).hexdigest()


def _operation_id(category: str, domain_id: str, record_id: str, revision: int, digest: str) -> str:
    material = "\0".join(("memory-delete-v1", category, domain_id, record_id, str(revision), digest))
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def write_tombstone(
    connection: sqlite3.Connection,
    *,
    category: str,
    domain_id: str,
    record_id: str,
    revision: int,
    body: str,
    deleted_at: datetime | str,
) -> dict[str, str | int | bool]:
    if category not in CATEGORY_TABLES or domain_id not in DOMAINS:
        raise ValueError("exclusão recusada")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("revisão inválida")
    if not isinstance(record_id, str) or len(record_id) != 32:
        raise ValueError("identificador inválido")
    if isinstance(deleted_at, datetime):
        if deleted_at.tzinfo is None or deleted_at.utcoffset() is None:
            raise ValueError("instante sem fuso")
        timestamp = deleted_at.astimezone(timezone.utc).isoformat()
    elif isinstance(deleted_at, str):
        timestamp = deleted_at
    else:
        raise ValueError("instante inválido")

    digest = content_digest(body)
    operation_id = _operation_id(category, domain_id, record_id, revision, digest)
    existing = connection.execute(
        """SELECT deleted_revision, content_sha256, operation_id
           FROM memory_deletion_tombstones
           WHERE category = ? AND domain_id = ? AND record_id = ?""",
        (category, domain_id, record_id),
    ).fetchone()
    if existing is not None:
        current_revision, current_digest, current_operation = existing
        if revision < current_revision:
            raise MemoryRevisionConflict("revisão antiga não pode desfazer exclusão")
        if revision == current_revision:
            if digest != current_digest:
                raise MemoryRevisionConflict("mesma revisão contém conteúdo incompatível")
            return {
                "operation_id": current_operation,
                "deleted_revision": current_revision,
                "idempotent": True,
            }
        connection.execute(
            """UPDATE memory_deletion_tombstones
               SET deleted_revision = ?, content_sha256 = ?, operation_id = ?, deleted_at = ?
               WHERE category = ? AND domain_id = ? AND record_id = ?""",
            (revision, digest, operation_id, timestamp, category, domain_id, record_id),
        )
    else:
        connection.execute(
            """INSERT INTO memory_deletion_tombstones(
                   category, record_id, domain_id, deleted_revision,
                   content_sha256, operation_id, deleted_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (category, record_id, domain_id, revision, digest, operation_id, timestamp),
        )
    return {"operation_id": operation_id, "deleted_revision": revision, "idempotent": False}


def repeat_deletion(
    connection: sqlite3.Connection,
    *, category: str, domain_id: str, record_id: str, expected_revision: int | None,
) -> dict[str, str | int | bool] | None:
    """Return the existing decision for a retried DELETE, or reject stale revisions."""
    row = connection.execute(
        """SELECT deleted_revision, operation_id FROM memory_deletion_tombstones
           WHERE category = ? AND domain_id = ? AND record_id = ?""",
        (category, domain_id, record_id),
    ).fetchone()
    if row is None:
        return None
    deleted_revision, operation_id = row
    if expected_revision is not None and expected_revision != deleted_revision:
        raise MemoryRevisionConflict("revisão desatualizada para item excluído")
    return {
        "operation_id": operation_id,
        "deleted_revision": deleted_revision,
        "idempotent": True,
    }


def apply_deletion_tombstones(connection: sqlite3.Connection, *, reject_newer_revision: bool = False) -> int:
    """Reapply deletions to a restored snapshot before it is published."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "memory_deletion_tombstones" not in tables:
        return 0
    removed = 0
    rows = connection.execute(
        """SELECT category, record_id, domain_id, deleted_revision, content_sha256
           FROM memory_deletion_tombstones
           ORDER BY category, domain_id, record_id"""
    ).fetchall()
    for category, record_id, domain_id, deleted_revision, expected_digest in rows:
        table = CATEGORY_TABLES.get(category)
        if table is None:
            raise MemoryRevisionConflict("tombstone com categoria inválida")
        row = connection.execute(
            f"SELECT body, version FROM {table} WHERE id = ? AND owner = 'owner' AND domain_id = ?",
            (record_id, domain_id),
        ).fetchone()
        if row is None:
            continue
        body, revision = row
        if revision < deleted_revision:
            remove = True
        elif revision == deleted_revision:
            actual_digest = content_digest(body)
            if actual_digest != expected_digest:
                raise MemoryRevisionConflict("mesma revisão contém conteúdo incompatível")
            remove = True
        else:
            if reject_newer_revision:
                raise MemoryRevisionConflict("linhagem da revisão posterior à exclusão não comprovada")
            remove = False
        if remove:
            connection.execute(
                f"DELETE FROM {table} WHERE id = ? AND owner = 'owner' AND domain_id = ?",
                (record_id, domain_id),
            )
            removed += 1
    return removed


def reconcile_deletion_tombstones(destination: sqlite3.Connection, current: sqlite3.Connection) -> None:
    """Union durable identities; clocks never arbitrate deletion conflicts.

    Different deletion revisions for one identity have no provable lineage in
    this ledger format. Refuse rather than silently losing either decision.
    """
    import re

    columns = "category, domain_id, record_id, deleted_revision, content_sha256, operation_id, deleted_at"
    decisions = {}
    for connection in (destination, current):
        for row in connection.execute(f"SELECT {columns} FROM memory_deletion_tombstones"):
            category, domain, identifier, revision, digest, operation, deleted_at = row
            if (category not in CATEGORY_TABLES or domain not in DOMAINS
                    or not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier)
                    or type(revision) is not int or revision < 1
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or operation != _operation_id(category, domain, identifier, revision, digest)):
                raise MemoryRevisionConflict("identidade de exclusão inválida")
            key = (category, domain, identifier)
            previous = decisions.get(key)
            if previous is not None and previous[3:6] != row[3:6]:
                raise MemoryRevisionConflict("exclusões conflitantes sem linhagem comprovada")
            decisions.setdefault(key, row)
    for row in decisions.values():
        destination.execute(f"INSERT OR IGNORE INTO memory_deletion_tombstones ({columns}) VALUES (?,?,?,?,?,?,?)", row)
