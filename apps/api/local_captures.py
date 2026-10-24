"""Capturas locais do proprietário sintético. Não criam missão nem saem da máquina.

Taxonomia deste armazenamento, só o que a tabela é hoje:
- explicit_capture: texto gravado diretamente pelo usuário.

O domínio autorizado deste caminho é dom_synthetic_a. A proveniência é o
identificador, esse domínio, a categoria e o instante local. Fato confirmado,
evidência de fonte externa e proposta inferida ficam em memory_categories.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import datetime, timezone

from memory_store import SQLiteMemoryStore

DOMAIN_ID = "dom_synthetic_a"
CATEGORY = "explicit_capture"
MAX_TEXT_CHARS = 80
MAX_STORED = 20
MAX_LISTED = 3
MAX_SEARCH_RESULTS = 3
_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,80}\Z")
_CAPTURE_ID = re.compile(r"[0-9a-f]{32}\Z")


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").casefold()


def _capture_id(value: str) -> bool:
    return isinstance(value, str) and _CAPTURE_ID.fullmatch(value) is not None


def _aware(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("instante sem fuso")
    return now.astimezone(timezone.utc).isoformat()


def create_capture(store: SQLiteMemoryStore, owner: str, text: str, now: datetime) -> dict[str, str]:
    if owner != "owner" or not isinstance(text, str) or _TEXT.fullmatch(text) is None:
        raise ValueError("captura recusada")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("captura recusada")
    created_at = _aware(now)
    capture_id = secrets.token_hex(16)
    with store.transaction() as connection:
        connection.execute(
            """INSERT INTO local_captures(id, owner, domain_id, body, created_at, revised_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (capture_id, owner, DOMAIN_ID, text, created_at, created_at),
        )
        stale = connection.execute(
            "SELECT id, version, body FROM local_captures WHERE owner = ? ORDER BY created_at DESC, id DESC",
            (owner,),
        ).fetchall()
        extra = [row[0] for row in stale[MAX_STORED:]]
        if extra:
            from memory_deletions import write_tombstone
            by_id = {row[0]: row for row in stale}
            for item in extra:
                row = by_id[item]
                write_tombstone(
                    connection, category=CATEGORY, domain_id=DOMAIN_ID, record_id=item,
                    revision=row[1], body=row[2], deleted_at=created_at,
                )
                connection.execute("DELETE FROM local_captures WHERE id = ?", (item,))
    return {"id": capture_id, "created_at": created_at, "domain_id": DOMAIN_ID, "text": text}


def list_captures(store: SQLiteMemoryStore, owner: str) -> list[dict[str, str]]:
    if owner != "owner":
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        rows = connection.execute(
            """SELECT id, body, created_at FROM local_captures
               WHERE owner = ? AND domain_id = ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (owner, DOMAIN_ID, MAX_LISTED),
        ).fetchall()
    return [{"id": row[0], "text": row[1], "created_at": row[2]} for row in rows]


def update_capture(
    store: SQLiteMemoryStore, owner: str, capture_id: str, text: str,
    expected_revision: int | None = None,
) -> dict[str, str | int]:
    if owner != "owner" or not _capture_id(capture_id) or not isinstance(text, str):
        raise ValueError("captura recusada")
    if _TEXT.fullmatch(text) is None or len(text) > MAX_TEXT_CHARS:
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT created_at, version FROM local_captures WHERE id = ? AND owner = ? AND domain_id = ?",
            (capture_id, owner, DOMAIN_ID),
        ).fetchone()
        if row is None:
            raise ValueError("captura recusada")
        if expected_revision is not None and row[1] != expected_revision:
            from memory_deletions import MemoryRevisionConflict
            raise MemoryRevisionConflict("revisão desatualizada")
        revised_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "UPDATE local_captures SET body = ?, version = version + 1, revised_at = ? WHERE id = ? AND owner = ?",
            (text, revised_at, capture_id, owner),
        )
    return {"id": capture_id, "created_at": row[0], "domain_id": DOMAIN_ID, "text": text,
            "version": row[1] + 1, "revised_at": revised_at}


def search_captures(store: SQLiteMemoryStore, owner: str, query: str) -> tuple[list[dict[str, str]], int]:
    """Literal substring search. The query is not an FTS or LIKE expression.

    The second value is how many matches were left out of this response.
    It is not a page cursor.
    """
    if owner != "owner" or not isinstance(query, str) or _TEXT.fullmatch(query) is None:
        raise ValueError("captura recusada")
    needle = _fold(query)
    with store.transaction() as connection:
        rows = connection.execute(
            """SELECT id, body, created_at, domain_id FROM local_captures
               WHERE owner = ? AND domain_id = ?
               ORDER BY created_at DESC, id DESC""",
            (owner, DOMAIN_ID),
        ).fetchall()
    matches = [
        {"id": row[0], "text": row[1], "created_at": row[2], "domain_id": row[3]}
        for row in rows
        if row[3] == DOMAIN_ID and needle in _fold(row[1])
    ]
    shown = matches[:MAX_SEARCH_RESULTS]
    return shown, len(matches) - len(shown)


def open_capture(store: SQLiteMemoryStore, owner: str, capture_id: str) -> dict[str, str]:
    if owner != "owner" or not _capture_id(capture_id):
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        row = connection.execute(
            """SELECT id, body, created_at, domain_id FROM local_captures
               WHERE id = ? AND owner = ? AND domain_id = ?""",
            (capture_id, owner, DOMAIN_ID),
        ).fetchone()
    if row is None or row[3] != DOMAIN_ID:
        raise ValueError("captura recusada")
    return {
        "id": row[0],
        "text": row[1],
        "created_at": row[2],
        "domain_id": row[3],
        "category": CATEGORY,
    }


def delete_capture(
    store: SQLiteMemoryStore, owner: str, capture_id: str, expected_revision: int | None = None,
) -> dict[str, str | int]:
    if owner != "owner" or not _capture_id(capture_id):
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT version, body FROM local_captures WHERE id = ? AND owner = ? AND domain_id = ?",
            (capture_id, owner, DOMAIN_ID),
        ).fetchone()
        if row is None:
            from memory_deletions import repeat_deletion
            repeated = repeat_deletion(
                connection, category=CATEGORY, domain_id=DOMAIN_ID, record_id=capture_id,
                expected_revision=expected_revision,
            )
            if repeated is not None:
                return {"id": capture_id, "domain_id": DOMAIN_ID,
                        "deleted_revision": repeated["deleted_revision"],
                        "operation_id": repeated["operation_id"], "idempotent": True}
            raise ValueError("captura recusada")
        if expected_revision is not None and row[0] != expected_revision:
            from memory_deletions import MemoryRevisionConflict
            raise MemoryRevisionConflict("revisão desatualizada")
        from memory_deletions import write_tombstone
        tombstone = write_tombstone(
            connection, category=CATEGORY, domain_id=DOMAIN_ID, record_id=capture_id,
            revision=row[0], body=row[1], deleted_at=datetime.now(timezone.utc),
        )
        deleted = connection.execute(
            "DELETE FROM local_captures WHERE id = ? AND owner = ? AND domain_id = ?",
            (capture_id, owner, DOMAIN_ID),
        ).rowcount
    if deleted != 1:
        raise ValueError("captura recusada")
    return {"id": capture_id, "domain_id": DOMAIN_ID, "deleted_revision": row[0],
            "operation_id": tombstone["operation_id"]}


def clear_captures(store: SQLiteMemoryStore, owner: str) -> int:
    if owner != "owner":
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        rows = connection.execute(
            "SELECT id, version, body FROM local_captures WHERE owner = ? AND domain_id = ?",
            (owner, DOMAIN_ID),
        ).fetchall()
        from memory_deletions import write_tombstone
        deleted_at = datetime.now(timezone.utc)
        for capture_id, revision, body in rows:
            write_tombstone(
                connection, category=CATEGORY, domain_id=DOMAIN_ID, record_id=capture_id,
                revision=revision, body=body, deleted_at=deleted_at,
            )
        deleted = connection.execute("DELETE FROM local_captures WHERE owner = ?", (owner,)).rowcount
    return max(deleted, 0)


def encode_capture_items(items: list[dict[str, str]]) -> str:
    lines = []
    for item in items:
        if any(char in "\t\n\r" for char in (*item["id"], *item["created_at"], *item["text"])):
            raise ValueError("captura recusada")
        lines.append(f"{item['id']}\t{item['created_at']}\t{item['text']}")
    return "\n".join(lines)
