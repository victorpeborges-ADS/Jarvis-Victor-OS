"""Ensaio de identidade e sync no processo. Não gera APK nem fala com aparelho.

O identificador de demonstração não é identidade. O transporte declarado é
in_process e o relay está ausente. Apagar tira o item do banco aberto; um
backup anterior pode conservar o texto. Uma operação posterior não regrava
esse item. Execução com o Mac desligado não é prometida.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from memory_categories import delete_memory
from memory_store import SQLiteMemoryStore

DEVICE_TEST = "NOT TESTED"
APK_BUILD = "NOT TESTED"
REMOTE_SEND = "BLOCKED"
TRANSPORT = "in_process"
RELAY_STORE = "ausente"
MAC_OFF_EXECUTION = "nao_prometido"
COST = "não medido"
LISTEN_SCOPE = "canal-sintetico"
OPEN_DOMAIN = "dom_synthetic_a"
TTL_SECONDS = 3600
_LABEL = "somente neste aparelho"
_ID = re.compile(r"[a-f0-9]{32}\Z")
_FINGERPRINT = re.compile(r"[a-f0-9]{64}\Z")
_SIGNATURE = re.compile(r"[a-f0-9]{128}\Z")
_PRESENTED = re.compile(r"[a-z0-9][a-z0-9-]{2,40}\Z")
_BODY = re.compile(r"[^\x00-\x1f\x7f]{1,80}\Z")
_UPSERT = frozenset({
    "op_id", "kind", "item_id", "domain_id", "body", "revision",
    "device_clock", "transport", "relay", "fingerprint", "signature",
})
_DELETE = _UPSERT - {"body"}
_CATEGORIES = frozenset({
    "confirmed_fact", "external_evidence", "inferred_proposal",
})


class MobileError(Exception):
    pass


def is_demo_identifier(value: str) -> bool:
    if not isinstance(value, str):
        return True
    folded = value.strip().lower()
    return folded in {"app.jarvis.mobile", "demo"} or folded.startswith(("demo-", "demo_"))


def product_memory(medium: str) -> str:
    if medium == "localStorage":
        raise MobileError("localStorage não é memória do produto")
    if medium != "sqlite-temporario":
        raise MobileError("armazenamento recusado")
    return medium


def build_apk() -> dict[str, str]:
    return {"status": APK_BUILD, "device": DEVICE_TEST, "path": ""}


def mac_execution(*, available: bool) -> dict[str, str | bool]:
    if not isinstance(available, bool):
        raise MobileError("execução recusada")
    status = "exige_mac" if available else "indisponivel"
    return {
        "status": status,
        "promised": False,
        "runs": False,
        "mac_off": MAC_OFF_EXECUTION,
        "cost": COST,
    }


def remote_note(identity: DeviceIdentity, *, kind: str, scope: str, body: str, now: int) -> dict[str, str | bool]:
    if kind in {"forwarded", "contact", "voice"}:
        raise MobileError("não autoriza")
    if kind != "message" or not isinstance(body, str) or _BODY.fullmatch(body) is None:
        raise MobileError("canal recusado")
    if not isinstance(identity, DeviceIdentity) or identity.status != "active":
        raise MobileError("remetente recusado")
    if isinstance(now, bool) or not isinstance(now, int) or now > identity.expires_at:
        raise MobileError("remetente recusado")
    if scope != identity.scope:
        raise MobileError("escopo separado")
    return {
        "accepted": True,
        "authorizes_effect": False,
        "sent": False,
        "status": REMOTE_SEND,
        "cost": COST,
    }


@dataclass
class DeviceIdentity:
    presented_id: str
    fingerprint: str
    public: bytes
    expires_at: int
    scope: str
    status: str
    _private: Ed25519PrivateKey | None

    def private_bytes(self) -> bytes:
        if self._private is None:
            raise MobileError("identidade recusada")
        return self._private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def signed(self, fields: dict[str, object]) -> dict[str, object]:
        if self.status != "active" or self._private is None:
            raise MobileError("identidade recusada")
        payload = dict(fields)
        payload["fingerprint"] = self.fingerprint
        signature = self._private.sign(_canonical(payload)).hex()
        payload["signature"] = signature
        return payload


def issue_identity(presented_id: str, *, now: int) -> DeviceIdentity:
    if is_demo_identifier(presented_id) or _PRESENTED.fullmatch(presented_id) is None:
        raise MobileError("identificador de demonstração não é identidade")
    if isinstance(now, bool) or not isinstance(now, int) or now < 0:
        raise MobileError("identidade recusada")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint = hashlib.sha256(public).hexdigest()
    if fingerprint == presented_id:
        raise MobileError("identificador de demonstração não é identidade")
    return DeviceIdentity(
        presented_id=presented_id,
        fingerprint=fingerprint,
        public=public,
        expires_at=now + TTL_SECONDS,
        scope=LISTEN_SCOPE,
        status="active",
        _private=private,
    )


class OpenSync:
    def __init__(self, path: Path) -> None:
        self.path = _guard(path)
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=DELETE")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS device_keys (
                fingerprint TEXT PRIMARY KEY,
                public_key BLOB NOT NULL,
                status TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                scope TEXT NOT NULL,
                presented_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_items (
                item_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                body TEXT NOT NULL,
                revision INTEGER NOT NULL,
                label TEXT NOT NULL,
                PRIMARY KEY (item_id, domain_id)
            );
            CREATE TABLE IF NOT EXISTS sync_deletions (
                item_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                removed_from_open_database INTEGER NOT NULL,
                historical_backup_may_keep_text INTEGER NOT NULL,
                PRIMARY KEY (item_id, domain_id)
            );
            CREATE TABLE IF NOT EXISTS sync_ops (
                op_id TEXT PRIMARY KEY,
                payload_sha256 TEXT NOT NULL,
                result TEXT NOT NULL
            );
            """
        )
        self.path.chmod(0o600)

    def close(self) -> None:
        self._connection.close()

    def enroll(self, identity: DeviceIdentity) -> None:
        if is_demo_identifier(identity.presented_id) or identity.presented_id == identity.fingerprint:
            raise MobileError("identificador de demonstração não é identidade")
        if identity.status != "active" or identity.scope != LISTEN_SCOPE:
            raise MobileError("identidade recusada")
        self._connection.execute(
            """INSERT INTO device_keys(
                   fingerprint, public_key, status, expires_at, scope, presented_id
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                identity.fingerprint,
                identity.public,
                identity.status,
                identity.expires_at,
                identity.scope,
                identity.presented_id,
            ),
        )
        self._connection.commit()

    def rotate(self, identity: DeviceIdentity, *, now: int) -> DeviceIdentity:
        self._set_status(identity.fingerprint, "rotated")
        identity.status = "rotated"
        identity._private = None
        fresh = issue_identity(identity.presented_id, now=now)
        self.enroll(fresh)
        return fresh

    def mark_lost(self, identity: DeviceIdentity) -> None:
        self._set_status(identity.fingerprint, "lost")
        identity.status = "lost"
        identity._private = None

    def revoke(self, identity: DeviceIdentity) -> None:
        self._set_status(identity.fingerprint, "revoked")
        identity.status = "revoked"
        identity._private = None

    def apply(self, identity: DeviceIdentity, op: dict[str, object], now: int) -> dict[str, object]:
        self._authorize(identity, op, now)
        payload_sha = hashlib.sha256(_canonical({key: op[key] for key in op if key != "signature"})).hexdigest()
        with self._connection:
            stored = self._connection.execute(
                "SELECT payload_sha256, result FROM sync_ops WHERE op_id = ?",
                (op["op_id"],),
            ).fetchone()
            if stored is not None:
                if stored["payload_sha256"] != payload_sha:
                    raise MobileError("operação divergente")
                return json.loads(stored["result"])
            result = self._effect(op)
            self._connection.execute(
                "INSERT INTO sync_ops(op_id, payload_sha256, result) VALUES (?, ?, ?)",
                (op["op_id"], payload_sha, json.dumps(result, ensure_ascii=False, sort_keys=True)),
            )
        return result

    def note_open_delete(
        self,
        store: SQLiteMemoryStore,
        identity: DeviceIdentity,
        op: dict[str, object],
        now: int,
        category: str,
    ) -> dict[str, object]:
        if category not in _CATEGORIES or op.get("kind") != "delete":
            raise MobileError("operação recusada")
        outcome = self.apply(identity, op, now)
        delete_memory(store, "owner", OPEN_DOMAIN, category, str(op["item_id"]))
        return outcome

    def read_item(self, item_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT body, revision, label, domain_id FROM sync_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "body": row["body"],
            "revision": row["revision"],
            "label": row["label"],
            "domain_id": row["domain_id"],
            "mac_ran": False,
        }

    def _set_status(self, fingerprint: str, status: str) -> None:
        updated = self._connection.execute(
            "UPDATE device_keys SET status = ? WHERE fingerprint = ?",
            (status, fingerprint),
        ).rowcount
        self._connection.commit()
        if updated != 1:
            raise MobileError("identidade recusada")

    def _authorize(self, identity: DeviceIdentity, op: dict[str, object], now: int) -> None:
        if isinstance(now, bool) or not isinstance(now, int):
            raise MobileError("operação recusada")
        fields = _DELETE if op.get("kind") == "delete" else _UPSERT
        if set(op) != fields:
            raise MobileError("operação recusada")
        if op["kind"] not in {"upsert", "delete"}:
            raise MobileError("operação recusada")
        if op["transport"] != TRANSPORT or op["relay"] != RELAY_STORE:
            raise MobileError("transporte não declarado")
        if op["domain_id"] != OPEN_DOMAIN:
            raise MobileError("domínio recusado")
        for name in ("op_id", "item_id"):
            if not isinstance(op[name], str) or _ID.fullmatch(op[name]) is None:
                raise MobileError("operação recusada")
        if not isinstance(op["fingerprint"], str) or _FINGERPRINT.fullmatch(op["fingerprint"]) is None:
            raise MobileError("identidade recusada")
        if not isinstance(op["signature"], str) or _SIGNATURE.fullmatch(op["signature"]) is None:
            raise MobileError("identidade recusada")
        if op["fingerprint"] != identity.fingerprint:
            raise MobileError("identidade recusada")
        _whole(op["revision"])
        _whole(op["device_clock"])
        if op["kind"] == "upsert" and (not isinstance(op["body"], str) or _BODY.fullmatch(op["body"]) is None):
            raise MobileError("operação recusada")
        row = self._connection.execute(
            "SELECT public_key, status, expires_at FROM device_keys WHERE fingerprint = ?",
            (identity.fingerprint,),
        ).fetchone()
        if row is None or row["status"] != "active" or now > row["expires_at"]:
            raise MobileError("dispositivo recusado")
        signed = {key: op[key] for key in op if key != "signature"}
        public = Ed25519PublicKey.from_public_bytes(row["public_key"])
        try:
            public.verify(bytes.fromhex(str(op["signature"])), _canonical(signed))
        except InvalidSignature as exc:
            raise MobileError("identidade recusada") from exc

    def _effect(self, op: dict[str, object]) -> dict[str, object]:
        item_id = str(op["item_id"])
        domain_id = str(op["domain_id"])
        revision = int(op["revision"])
        deleted = self._connection.execute(
            "SELECT revision FROM sync_deletions WHERE item_id = ? AND domain_id = ?",
            (item_id, domain_id),
        ).fetchone()
        if op["kind"] == "delete" or deleted is not None:
            if op["kind"] == "delete":
                self._connection.execute(
                    "DELETE FROM sync_items WHERE item_id = ? AND domain_id = ?",
                    (item_id, domain_id),
                )
                self._connection.execute(
                    """INSERT INTO sync_deletions(
                           item_id, domain_id, revision,
                           removed_from_open_database, historical_backup_may_keep_text
                       ) VALUES (?, ?, ?, 1, 1)
                       ON CONFLICT(item_id, domain_id) DO UPDATE SET
                           revision = max(sync_deletions.revision, excluded.revision)""",
                    (item_id, domain_id, revision),
                )
            return {
                "status": "apagado",
                "resurrected": False,
                "removed_from_open_database": True,
                "historical_backup_may_keep_text": True,
                "mac_ran": False,
                "cost": COST,
            }
        current = self._connection.execute(
            "SELECT body, revision FROM sync_items WHERE item_id = ? AND domain_id = ?",
            (item_id, domain_id),
        ).fetchone()
        body = str(op["body"])
        if current is None:
            self._connection.execute(
                """INSERT INTO sync_items(item_id, domain_id, body, revision, label)
                   VALUES (?, ?, ?, ?, ?)""",
                (item_id, domain_id, body, revision, _LABEL),
            )
            return _applied()
        if revision < int(current["revision"]) or (
            revision == int(current["revision"]) and body != current["body"]
        ):
            status = "ignorado" if revision < int(current["revision"]) else "conflito"
            return {
                "status": status,
                "resurrected": False,
                "mac_ran": False,
                "cost": COST,
            }
        if body != current["body"]:
            self._connection.execute(
                """UPDATE sync_items SET body = ?, revision = ?
                   WHERE item_id = ? AND domain_id = ?""",
                (body, revision, item_id, domain_id),
            )
        return _applied()


def _applied() -> dict[str, object]:
    return {
        "status": "aplicado",
        "resurrected": False,
        "label": _LABEL,
        "mac_ran": False,
        "cost": COST,
    }


def _whole(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1_000_000_000_000:
        raise MobileError("operação recusada")


def _canonical(fields: dict[str, object]) -> bytes:
    return json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _guard(path: Path) -> Path:
    resolved = path.resolve()
    lowered = str(resolved).replace("\\", "/")
    markers = (
        "/Library/Application Support/Jarvis",
        "/.codex/worktrees/",
        "/uv/",
        "localStorage",
    )
    if any(marker in lowered for marker in markers):
        raise MobileError("caminho recusado")
    return resolved
