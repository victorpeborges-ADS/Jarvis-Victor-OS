"""Persistência mínima do identificador opaco de conversa.

Somente o id, domínio e horários de criação/atividade/expiração são guardados
no snapshot cifrado. Mensagens, respostas, prompts, fontes e autorização nunca
são persistidos. A validade é deslizante por 24 horas de inatividade.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from memory_categories import DOMAINS
from memory_store import SQLiteMemoryStore

CONVERSATION_TTL = timedelta(hours=24)
_CONVERSATION_ID = re.compile(r"[0-9a-f]{32}\Z")
_MODES = frozenset({"resume", "new"})


def open_conversation(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    mode: str,
    now: datetime,
) -> dict[str, str]:
    if owner != "owner" or domain_id not in DOMAINS or mode not in _MODES:
        raise ValueError("conversa recusada")
    current = _moment(now)
    expires = _moment(now.astimezone(timezone.utc) + CONVERSATION_TTL)
    with store.transaction() as connection:
        connection.execute(
            "DELETE FROM local_conversations WHERE expires_at <= ?", (current,),
        )
        if mode == "resume":
            row = connection.execute(
                """SELECT conversation_id FROM local_conversations
                   WHERE owner=? AND domain_id=? AND expires_at>?
                   ORDER BY last_seen_at DESC, created_at DESC LIMIT 1""",
                (owner, domain_id, current),
            ).fetchone()
            if row is not None:
                conversation_id = row[0]
                connection.execute(
                    """UPDATE local_conversations SET last_seen_at=?, expires_at=?
                       WHERE conversation_id=? AND owner=? AND domain_id=?""",
                    (current, expires, conversation_id, owner, domain_id),
                )
                return {"conversation_id": conversation_id, "expires_at": expires}

        for _attempt in range(3):
            conversation_id = secrets.token_hex(16)
            try:
                connection.execute(
                    """INSERT INTO local_conversations(
                           conversation_id, owner, domain_id, created_at, last_seen_at, expires_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (conversation_id, owner, domain_id, current, current, expires),
                )
                return {"conversation_id": conversation_id, "expires_at": expires}
            except sqlite3.IntegrityError:
                continue
        raise ValueError("conversa recusada")


def touch_conversation(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    conversation_id: str,
    now: datetime,
) -> str | None:
    if (
        owner != "owner"
        or domain_id not in DOMAINS
        or not isinstance(conversation_id, str)
        or _CONVERSATION_ID.fullmatch(conversation_id) is None
    ):
        return None
    current = _moment(now)
    expires = _moment(now.astimezone(timezone.utc) + CONVERSATION_TTL)
    with store.transaction() as connection:
        cursor = connection.execute(
            """UPDATE local_conversations SET last_seen_at=?, expires_at=?
               WHERE conversation_id=? AND owner=? AND domain_id=? AND expires_at>?""",
            (current, expires, conversation_id, owner, domain_id, current),
        )
        return expires if cursor.rowcount == 1 else None


def conversation_exists(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    conversation_id: str,
    now: datetime,
) -> bool:
    """Check a persisted id without extending its inactivity window."""
    if (
        owner != "owner"
        or domain_id not in DOMAINS
        or not isinstance(conversation_id, str)
        or _CONVERSATION_ID.fullmatch(conversation_id) is None
    ):
        return False
    current = _moment(now)
    with store.transaction() as connection:
        row = connection.execute(
            """SELECT 1 FROM local_conversations
               WHERE conversation_id=? AND owner=? AND domain_id=? AND expires_at>?""",
            (conversation_id, owner, domain_id, current),
        ).fetchone()
    return row is not None


def _moment(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("conversa recusada")
    return value.astimezone(timezone.utc).isoformat()
