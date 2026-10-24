"""Artefatos sintéticos cifrados no store e leitura por fragmentos limitados."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from conversation_gateway import APP_RESPONSE_MAX_BYTES
from memory_categories import DOMAINS
from memory_store import SQLiteMemoryStore
from skill_registry import canonical_json

MAX_ARTIFACT_BYTES = 65536
MAX_FRAGMENT_BYTES = 512
_HEX_ID = re.compile(r"[0-9a-f]{32}\Z")
_HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ORIGIN_ID = "generate-synthetic-document"
_VERSION = "1.0.0"


def put_artifact(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    body: bytes,
    now: datetime,
    retain_until: datetime,
    *,
    origin_id: str = _ORIGIN_ID,
    version: str = _VERSION,
    manifest_sha256: str = "0" * 64,
) -> dict[str, str | int]:
    if owner != "owner" or domain_id not in DOMAINS:
        raise ValueError("artefato recusado")
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_ARTIFACT_BYTES:
        raise ValueError("artefato recusado")
    if (
        origin_id != _ORIGIN_ID
        or version != _VERSION
        or not isinstance(manifest_sha256, str)
        or _HEX_SHA.fullmatch(manifest_sha256) is None
    ):
        raise ValueError("artefato recusado")
    if now.tzinfo is None or now.utcoffset() is None or retain_until.tzinfo is None or retain_until.utcoffset() is None:
        raise ValueError("artefato recusado")
    if retain_until <= now:
        raise ValueError("artefato recusado")
    digest = hashlib.sha256(body).hexdigest()
    artifact_id = secrets.token_hex(16)
    created_at = now.astimezone(timezone.utc).isoformat()
    expires_at = retain_until.astimezone(timezone.utc).isoformat()
    with store.transaction() as connection:
        connection.execute(
            """INSERT INTO synthetic_artifacts(
                   id, owner, domain_id, origin_id, version, manifest_sha256,
                   sha256, size, body, retain_until, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (artifact_id, owner, domain_id, origin_id, version, manifest_sha256,
             digest, len(body), body, expires_at, created_at),
        )
    return {
        "id": artifact_id,
        "domain_id": domain_id,
        "origin_id": origin_id,
        "version": version,
        "manifest_sha256": manifest_sha256,
        "sha256": digest,
        "size": len(body),
    }


def read_verified_artifact(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    artifact_id: str,
    expected_manifest_sha256: str,
    now: datetime,
) -> dict[str, str] | None:
    if (
        owner != "owner"
        or domain_id not in DOMAINS
        or not _hex_id(artifact_id)
        or not isinstance(expected_manifest_sha256, str)
        or _HEX_SHA.fullmatch(expected_manifest_sha256) is None
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        return None
    with store.transaction() as connection:
        row = connection.execute(
            """SELECT domain_id, origin_id, version, manifest_sha256,
                      sha256, size, body, retain_until
               FROM synthetic_artifacts WHERE id=? AND owner=?""",
            (artifact_id, owner),
        ).fetchone()
    if row is None:
        return None
    domain, origin_id, version, manifest_hash, digest, size, raw, retain_until = row
    body = bytes(raw)
    if (
        domain != domain_id
        or origin_id != _ORIGIN_ID
        or version != _VERSION
        or manifest_hash != expected_manifest_sha256
        or size != len(body)
        or not 1 <= size <= MAX_ARTIFACT_BYTES
        or hashlib.sha256(body).hexdigest() != digest
        or now.astimezone(timezone.utc).isoformat() >= retain_until
    ):
        return None
    try:
        artifact = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    if canonical_json(artifact).encode("utf-8") != body or not _artifact_matches(artifact, artifact_id, manifest_hash):
        return None
    content = "\n".join(
        line
        for section in artifact["sections"]
        for line in (section["heading"], *section["paragraphs"])
    )
    return {
        "id": artifact_id,
        "domain_id": domain,
        "origin_id": origin_id,
        "version": version,
        "manifest_sha256": manifest_hash,
        "sha256": digest,
        "text": content,
    }


def read_fragment(
    store: SQLiteMemoryStore,
    owner: str,
    domain_id: str,
    artifact_id: str,
    offset: int,
    length: int,
    now: datetime,
) -> dict[str, str | int]:
    refused = {"status": "artifact_rejected", "id": "", "sha256": "", "offset": 0, "data_hex": ""}
    if owner != "owner" or domain_id not in DOMAINS or not _hex_id(artifact_id):
        return refused
    if isinstance(offset, bool) or isinstance(length, bool) or not isinstance(offset, int) or not isinstance(length, int):
        return refused
    if offset < 0 or not 1 <= length <= MAX_FRAGMENT_BYTES or now.tzinfo is None or now.utcoffset() is None:
        return refused
    with store.transaction() as connection:
        row = connection.execute(
            """SELECT sha256, size, body, retain_until, domain_id
               FROM synthetic_artifacts WHERE id = ? AND owner = ?""",
            (artifact_id, owner),
        ).fetchone()
    if row is None or row[4] != domain_id:
        return {**refused, "status": "domain_rejected"}
    if now.astimezone(timezone.utc).isoformat() >= row[3]:
        return {**refused, "status": "expired", "id": artifact_id}
    if row[1] != len(row[2]) or hashlib.sha256(bytes(row[2])).hexdigest() != row[0]:
        return {**refused, "status": "artifact_rejected", "id": artifact_id}
    if offset >= row[1]:
        return refused
    payload = {
        "status": "fragment", "id": artifact_id, "sha256": row[0],
        "offset": offset, "data_hex": bytes(row[2][offset:offset + length]).hex(),
    }
    if len(_encoded(payload)) > APP_RESPONSE_MAX_BYTES:
        return {**refused, "status": "response_too_large", "id": artifact_id, "sha256": row[0]}
    return payload


def _artifact_matches(value: object, artifact_id: str, manifest_sha256: str) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "id", "schema_version", "kind", "title", "sections", "origin", "permission",
    }:
        return False
    if (
        not isinstance(value["id"], str)
        or re.fullmatch(r"doc_[0-9a-f]{16}", value["id"]) is None
        or value["schema_version"] != 1
        or value["kind"] != "synthetic_document"
        or not _bounded_plain(value["title"], 120)
    ):
        return False
    if value["origin"] != {
        "skill_id": _ORIGIN_ID, "skill_version": _VERSION,
        "manifest_sha256": manifest_sha256,
        "license_name": "nao-declarada-no-arquivo-local",
    } or value["permission"] != {
        "capability": "generate_synthetic_document", "scope": "synthetic", "principal": "owner",
    }:
        return False
    sections = value["sections"]
    if not isinstance(sections, list) or not 1 <= len(sections) <= 6:
        return False
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict) or set(section) != {"index", "heading", "paragraphs", "source_id"}:
            return False
        paragraphs = section["paragraphs"]
        if (
            section["index"] != index
            or not _bounded_plain(section["heading"], 80)
            or not isinstance(paragraphs, list)
            or not 1 <= len(paragraphs) <= 4
            or not all(_bounded_plain(item, 400) for item in paragraphs)
            or not isinstance(section["source_id"], str)
            or re.fullmatch(r"src_[a-z0-9_]{1,40}", section["source_id"]) is None
        ):
            return False
    document = {key: item for key, item in value.items() if key != "id"}
    expected_id = "doc_" + hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()[:16]
    return value["id"] == expected_id and canonical_json(value).encode("utf-8") == _canonical_bytes(value)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _bounded_plain(value: object, maximum: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum and not any(
        ord(char) < 0x20 or ord(char) == 0x7f for char in value
    )


def _encoded(payload: dict[str, str | int]) -> bytes:
    pairs = (
        ("status", str(payload["status"])), ("id", str(payload["id"])),
        ("sha256", str(payload["sha256"])), ("offset", str(payload["offset"])),
        ("data_hex", str(payload["data_hex"])),
    )
    return "".join(f"{name}={quote(value, safe='')}\n" for name, value in pairs).encode("ascii")


def _hex_id(value: object) -> bool:
    return isinstance(value, str) and _HEX_ID.fullmatch(value) is not None
