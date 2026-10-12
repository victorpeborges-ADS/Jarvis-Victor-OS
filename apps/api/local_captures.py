"""Capturas locais do proprietário sintético. Não criam missão nem saem da máquina."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from memory_store import SQLiteMemoryStore

DOMAIN_ID = "dom_synthetic_a"
MAX_TEXT_CHARS = 80
MAX_STORED = 20
MAX_LISTED = 3
_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,80}\Z")


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
            "INSERT INTO local_captures(id, owner, domain_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (capture_id, owner, DOMAIN_ID, text, created_at),
        )
        stale = connection.execute(
            "SELECT id FROM local_captures WHERE owner = ? ORDER BY created_at DESC, id DESC",
            (owner,),
        ).fetchall()
        extra = [row[0] for row in stale[MAX_STORED:]]
        if extra:
            connection.executemany("DELETE FROM local_captures WHERE id = ?", [(item,) for item in extra])
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


def update_capture(store: SQLiteMemoryStore, owner: str, capture_id: str, text: str) -> dict[str, str]:
    if owner != "owner" or not isinstance(capture_id, str) or not isinstance(text, str):
        raise ValueError("captura recusada")
    if len(capture_id) != 32 or any(character not in "0123456789abcdef" for character in capture_id):
        raise ValueError("captura recusada")
    if _TEXT.fullmatch(text) is None or len(text) > MAX_TEXT_CHARS:
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT created_at FROM local_captures WHERE id = ? AND owner = ? AND domain_id = ?",
            (capture_id, owner, DOMAIN_ID),
        ).fetchone()
        if row is None:
            raise ValueError("captura recusada")
        connection.execute(
            "UPDATE local_captures SET body = ? WHERE id = ? AND owner = ?",
            (text, capture_id, owner),
        )
    return {"id": capture_id, "created_at": row[0], "domain_id": DOMAIN_ID, "text": text}


def delete_capture(store: SQLiteMemoryStore, owner: str, capture_id: str) -> None:
    if owner != "owner" or not isinstance(capture_id, str):
        raise ValueError("captura recusada")
    if len(capture_id) != 32 or any(character not in "0123456789abcdef" for character in capture_id):
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        deleted = connection.execute(
            "DELETE FROM local_captures WHERE id = ? AND owner = ? AND domain_id = ?",
            (capture_id, owner, DOMAIN_ID),
        ).rowcount
    if deleted != 1:
        raise ValueError("captura recusada")


def clear_captures(store: SQLiteMemoryStore, owner: str) -> int:
    if owner != "owner":
        raise ValueError("captura recusada")
    with store.transaction() as connection:
        deleted = connection.execute("DELETE FROM local_captures WHERE owner = ?", (owner,)).rowcount
    return max(deleted, 0)


def encode_capture_items(items: list[dict[str, str]]) -> str:
    lines = []
    for item in items:
        if any(char in "\t\n\r" for char in (*item["id"], *item["created_at"], *item["text"])):
            raise ValueError("captura recusada")
        lines.append(f"{item['id']}\t{item['created_at']}\t{item['text']}")
    return "\n".join(lines)
