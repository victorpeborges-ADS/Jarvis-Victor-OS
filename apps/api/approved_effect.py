"""Efeito preparado num serviço falso. Não envia mensagem e não abre rede.

Retry devolve a mesma linha. Versão nova de plano não reutiliza aprovação.
Cancelar depois do efeito confirmado não o marca como cancelado. O smoke da
janela continua bloqueado: este módulo não o transforma em passe.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone

from memory_categories import DOMAINS
from memory_store import SQLiteMemoryStore

WINDOW_SMOKE = "BLOCKED"
_RECIPIENT = re.compile(r"[a-z0-9._-]{1,40}@example\.test\Z")
_VERSION = re.compile(r"[A-Za-z0-9._-]{1,32}\Z")
_MEASURED = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?\Z")
QUIET_START = 22
QUIET_END = 7
NOTICE_CAP = 3
LATE_GRACE_SECONDS = 300


def dry_run(version: str, recipient: str, content: str) -> dict[str, str]:
    _check(version, recipient, content)
    return {
        "version": version,
        "recipient": recipient,
        "content": content,
        "effect": "rascunho local sem envio",
        "precondition": "aprovação da mesma versão",
        "dispatched": "false",
    }


def approval_sha(version: str, recipient: str, content: str) -> str:
    _check(version, recipient, content)
    raw = f"{version}\n{recipient}\n{content}\nrascunho local sem envio"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prepare_effect(
    store: SQLiteMemoryStore,
    domain_id: str,
    version: str,
    recipient: str,
    content: str,
    presented_sha: str,
) -> dict[str, str | int]:
    if domain_id not in DOMAINS or presented_sha != approval_sha(version, recipient, content):
        raise ValueError("efeito recusado")
    effect_key = hashlib.sha256(f"{domain_id}\n{presented_sha}".encode("utf-8")).hexdigest()
    with store.transaction() as connection:
        existing = connection.execute(
            "SELECT id, status, confirmed FROM prepared_effects WHERE effect_key = ?",
            (effect_key,),
        ).fetchone()
        if existing is not None:
            return _row(existing[0], version, recipient, content, existing[1], existing[2])
        effect_id = secrets.token_hex(16)
        connection.execute(
            """INSERT INTO prepared_effects(
                   id, owner, domain_id, recipient, content, plan_version,
                   approval_sha, effect_key, status, confirmed
               ) VALUES (?, 'owner', ?, ?, ?, ?, ?, ?, 'prepared', 0)""",
            (effect_id, domain_id, recipient, content, version, presented_sha, effect_key),
        )
    return _row(effect_id, version, recipient, content, "prepared", 0)


def dispatch_effect(
    store: SQLiteMemoryStore,
    domain_id: str,
    effect_id: str,
    version: str,
) -> dict[str, str | int]:
    with store.transaction() as connection:
        row = _load(connection, domain_id, effect_id)
        if row[3] != version or row[4] != "prepared" or row[5] != 0:
            raise ValueError("efeito recusado")
        connection.execute(
            "UPDATE prepared_effects SET status = 'succeeded', confirmed = 1 WHERE id = ?",
            (effect_id,),
        )
    return _row(effect_id, version, row[1], row[2], "succeeded", 1)


def retry_dispatch(
    store: SQLiteMemoryStore,
    domain_id: str,
    effect_id: str,
    version: str,
) -> dict[str, str | int]:
    with store.transaction() as connection:
        row = _load(connection, domain_id, effect_id)
        if row[3] != version or row[4] != "succeeded" or row[5] != 1:
            raise ValueError("efeito recusado")
        count = connection.execute(
            "SELECT COUNT(*) FROM prepared_effects WHERE effect_key = ?",
            (hashlib.sha256(f"{domain_id}\n{row[6]}".encode("utf-8")).hexdigest(),),
        ).fetchone()[0]
    if count != 1:
        raise ValueError("efeito recusado")
    return _row(effect_id, version, row[1], row[2], "succeeded", 1)


def revoke_effect(store: SQLiteMemoryStore, domain_id: str, effect_id: str) -> None:
    with store.transaction() as connection:
        row = _load(connection, domain_id, effect_id)
        if row[5] == 1:
            raise ValueError("efeito recusado")
        connection.execute(
            "UPDATE prepared_effects SET status = 'revoked' WHERE id = ? AND confirmed = 0",
            (effect_id,),
        )


def cancel_effect(store: SQLiteMemoryStore, domain_id: str, effect_id: str) -> str:
    with store.transaction() as connection:
        row = _load(connection, domain_id, effect_id)
        if row[5] == 1 or row[4] == "succeeded":
            return "succeeded"
        connection.execute(
            "UPDATE prepared_effects SET status = 'cancelled' WHERE id = ? AND confirmed = 0",
            (effect_id,),
        )
    return "cancelled"


def submit_notice(
    store: SQLiteMemoryStore,
    fingerprint: str,
    now: datetime,
    *,
    quiet: bool,
    late_seconds: int,
    cost: str,
    foreground: bool,
) -> dict[str, str]:
    if now.tzinfo is None or not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("aviso recusado")
    if cost != "não medido" and _MEASURED.fullmatch(cost) is None:
        raise ValueError("aviso recusado")
    if foreground:
        return _insert_notice(store, fingerprint, "suppressed", cost, replace=False)
    if quiet or _in_quiet_hours(now):
        return _insert_notice(store, fingerprint, "deferred", cost, replace=False)
    if late_seconds > LATE_GRACE_SECONDS:
        return _insert_notice(store, fingerprint, "missed", cost, replace=True)
    with store.transaction() as connection:
        open_count = connection.execute(
            """SELECT COUNT(*) FROM attention_notices
               WHERE owner = 'owner' AND status IN ('pending', 'deferred', 'delivered')"""
        ).fetchone()[0]
    if open_count >= NOTICE_CAP:
        raise ValueError("aviso recusado")
    return _insert_notice(store, fingerprint, "delivered", cost, replace=False)


def _insert_notice(
    store: SQLiteMemoryStore,
    fingerprint: str,
    status: str,
    cost: str,
    *,
    replace: bool,
) -> dict[str, str]:
    with store.transaction() as connection:
        existing = connection.execute(
            """SELECT id, status, cost FROM attention_notices
               WHERE owner = 'owner' AND fingerprint = ?
                 AND status IN ('pending', 'deferred', 'delivered', 'suppressed')""",
            (fingerprint,),
        ).fetchone()
        if existing is not None and not replace:
            return {"id": existing[0], "status": existing[1], "cost": existing[2]}
        notice_id = secrets.token_hex(16)
        connection.execute(
            """INSERT INTO attention_notices(id, owner, fingerprint, status, cost)
               VALUES (?, 'owner', ?, ?, ?)""",
            (notice_id, fingerprint, status, cost),
        )
    return {"id": notice_id, "status": status, "cost": cost}


def _check(version: str, recipient: str, content: str) -> None:
    if not isinstance(content, str) or not 1 <= len(content) <= 400:
        raise ValueError("efeito recusado")
    if _VERSION.fullmatch(version) is None or _RECIPIENT.fullmatch(recipient) is None:
        raise ValueError("efeito recusado")


def _load(connection, domain_id: str, effect_id: str):
    row = connection.execute(
        """SELECT id, recipient, content, plan_version, status, confirmed, approval_sha
           FROM prepared_effects
           WHERE id = ? AND owner = 'owner' AND domain_id = ?""",
        (effect_id, domain_id),
    ).fetchone()
    if row is None:
        raise ValueError("efeito recusado")
    return row


def _row(effect_id: str, version: str, recipient: str, content: str, status: str, confirmed: int) -> dict[str, str | int]:
    return {
        "id": effect_id,
        "version": version,
        "recipient": recipient,
        "content": content,
        "status": status,
        "confirmed": confirmed,
    }


def _in_quiet_hours(now: datetime) -> bool:
    hour = now.astimezone(timezone.utc).hour
    return hour >= QUIET_START or hour < QUIET_END
