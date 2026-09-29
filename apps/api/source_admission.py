"""Canonical source proof and fail-closed projections for local API records.

Persisted classification, selection, and review strings are claims. This module
reconstructs trust from the server catalog, linked mission, knowledge row,
review snapshot, and local decision ledger before any API surface uses them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from source_catalog import CATALOG_ID, CATALOG_VERSION, FIXTURES


DECISIONS = {"approved", "rejected", "changes_requested"}
_LEGACY_NULL_FIELDS = ("fixture_id", "catalog_id", "catalog_version", "fixture_sha256", "provenance_json")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _value(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _json_object(value) -> dict | None:
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else None
    except (TypeError, ValueError):
        return None


def _artifact_payload(value: dict) -> dict:
    """Review state is a projection; all other snapshot fields are immutable."""
    return {key: item for key, item in value.items() if key not in {"review_state", "reviewed_at"}}


@dataclass(frozen=True)
class SourceProof:
    trusted: bool
    source: object | None = None
    fixture: dict | None = None
    knowledge: object | None = None
    review: object | None = None
    mission: object | None = None
    artifact: dict | None = None


def _source_rows(connection, source_id: str, owner: str):
    source = connection.execute(
        "SELECT * FROM selected_synthetic_sources WHERE id=? AND owner=?",
        (source_id, owner),
    ).fetchone()
    if source is None:
        return None, None, None, None
    mission = connection.execute(
        "SELECT id, owner, domain_id, document_json FROM missions WHERE id=? AND owner=?",
        (source["mission_id"], owner),
    ).fetchone()
    knowledge = connection.execute(
        "SELECT * FROM mission_knowledge WHERE id=? AND owner=? AND mission_id=?",
        (source["knowledge_id"], owner, source["mission_id"]),
    ).fetchone()
    review = connection.execute(
        "SELECT * FROM mission_artifact_reviews WHERE id=? AND owner=? AND mission_id=?",
        (source["review_id"], owner, source["mission_id"]),
    ).fetchone()
    return source, mission, knowledge, review


def _linked_snapshot_proof(connection, source, owner: str, fixture: dict):
    """Validate links and canonical bytes; never infer a relationship from IDs alone."""
    if source["owner"] != owner or source["classification"] != "synthetic_verified" or source["state"] != "selected":
        return None
    if any(source[field] is None for field in _LEGACY_NULL_FIELDS):
        return None
    if (
        source["fixture_id"] != fixture["id"]
        or source["catalog_id"] != CATALOG_ID
        or source["catalog_version"] != CATALOG_VERSION
        or source["fixture_sha256"] != fixture["content_sha256"]
        or source["content_sha256"] != fixture["content_sha256"]
        or source["display_name"] != fixture["display_name"]
        or source["byte_count"] != len(fixture["content"].encode("utf-8"))
    ):
        return None
    provenance = _json_object(source["provenance_json"])
    if provenance != fixture["provenance"]:
        return None

    source_row, mission, knowledge, review = _source_rows(connection, source["id"], owner)
    if source_row is None or mission is None or knowledge is None or review is None:
        return None
    if (
        mission["id"] != source["mission_id"]
        or mission["owner"] != source["owner"]
        or mission["domain_id"] != source["domain_id"]
        or knowledge["id"] != source["knowledge_id"]
        or knowledge["owner"] != owner
        or knowledge["mission_id"] != source["mission_id"]
        or knowledge["domain_id"] != source["domain_id"]
        or knowledge["kind"] != "selected_original"
        or knowledge["source_review_id"] != source["review_id"]
        or knowledge["content"] != fixture["content"]
        or review["id"] != source["review_id"]
        or review["owner"] != owner
        or review["mission_id"] != source["mission_id"]
        or review["domain_id"] != source["domain_id"]
        or review["artifact_version"] != 1
    ):
        return None

    snapshot = _json_object(review["artifact_snapshot_json"])
    if snapshot is None or _digest(snapshot) != review["artifact_sha256"]:
        return None
    expected_ref = f"synthetic:selected:{source['id']}"
    refs = snapshot.get("source_refs")
    if not isinstance(refs, list) or not any(
        isinstance(ref, dict) and ref.get("source_id") == expected_ref
        and ref.get("domain_id") == source["domain_id"]
        for ref in refs
    ):
        return None
    if (
        snapshot.get("id") != review["artifact_id"]
        or snapshot.get("kind") != "evidence"
        or snapshot.get("skill_id") != "selected-synthetic-file"
        or snapshot.get("content") != fixture["content"]
        or snapshot.get("input_digest") != fixture["content_sha256"]
        or snapshot.get("title") != f"Fonte sintética selecionada: {fixture['display_name']}"
    ):
        return None

    mission_doc = _json_object(mission["document_json"])
    if mission_doc is None or mission_doc.get("id") != mission["id"] or mission_doc.get("domain_id") != source["domain_id"]:
        return None
    artifacts = mission_doc.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    matching = [artifact for artifact in artifacts if isinstance(artifact, dict)
                and artifact.get("id") == review["artifact_id"]]
    if len(matching) != 1 or _artifact_payload(matching[0]) != _artifact_payload(snapshot):
        return None
    return mission, knowledge, review, snapshot, matching[0]


def prove_source(connection, source_or_id, owner: str, mission_id: str | None = None) -> SourceProof:
    """Rebuild the complete R4 source proof for one owner-scoped source row."""
    source_id = source_or_id if isinstance(source_or_id, str) else _value(source_or_id, "id")
    if not isinstance(source_id, str):
        return SourceProof(False)
    source, mission, knowledge, review = _source_rows(connection, source_id, owner)
    if source is None or (mission_id is not None and source["mission_id"] != mission_id):
        return SourceProof(False, source=source)
    fixture_id = _value(source, "fixture_id")
    fixture = FIXTURES.get(fixture_id) if isinstance(fixture_id, str) else None
    if fixture is None:
        return SourceProof(False, source=source, mission=mission, knowledge=knowledge, review=review)
    links = _linked_snapshot_proof(connection, source, owner, fixture)
    if links is None:
        return SourceProof(False, source=source, fixture=fixture, mission=mission,
                           knowledge=knowledge, review=review)
    mission, knowledge, review, snapshot, artifact = links
    return SourceProof(True, source=source, fixture=fixture, knowledge=knowledge,
                       review=review, mission=mission, artifact=artifact)


def source_matches_fixture(source, fixture: dict, content: str) -> bool:
    """Compatibility helper for callers with a source projection and exact bytes."""
    try:
        return (
            source["classification"] == "synthetic_verified"
            and source["state"] == "selected"
            and source["fixture_id"] == fixture["id"]
            and source["catalog_id"] == CATALOG_ID
            and source["catalog_version"] == CATALOG_VERSION
            and source["fixture_sha256"] == fixture["content_sha256"]
            and source["content_sha256"] == fixture["content_sha256"] == _sha_text(content)
            and source["byte_count"] == len(content.encode("utf-8"))
            and source["display_name"] == fixture["display_name"]
            and _json_object(source["provenance_json"]) == fixture["provenance"]
            and content == fixture["content"]
        )
    except (KeyError, TypeError, ValueError):
        return False


def legacy_source_fixture(connection, source) -> dict | None:
    """Prove only migration candidates whose old schema stored a linked snapshot."""
    try:
        if source["classification"] != "unverified" or source["state"] != "quarantined":
            return None
        if any(source[field] is not None for field in _LEGACY_NULL_FIELDS):
            return None
        source_row, mission, knowledge, review = _source_rows(connection, source["id"], source["owner"])
        if source_row is None or mission is None or knowledge is None or review is None:
            return None
        content = knowledge["content"]
        candidates = [item for item in FIXTURES.values()
                      if item["content"] == content
                      and item["content_sha256"] == source["content_sha256"]
                      and len(content.encode("utf-8")) == source["byte_count"]]
        if len(candidates) != 1:
            return None
        fixture = dict(candidates[0])
        # Validate old-schema links without treating absent catalog columns as proof.
        temporary = dict(source)
        temporary.update({
            "classification": "synthetic_verified", "state": "selected",
            "fixture_id": fixture["id"], "catalog_id": CATALOG_ID,
            "catalog_version": CATALOG_VERSION, "fixture_sha256": fixture["content_sha256"],
            "provenance_json": _canonical_json(fixture["provenance"]),
            "display_name": fixture["display_name"],
        })
        # The row may be sqlite.Row, so use the temporary mapping for the common verifier.
        links = _linked_snapshot_proof(connection, temporary, source["owner"], fixture)
        return fixture if links is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def canonical_review_state(connection, review) -> tuple[str, bool, dict | None]:
    """Return the state proven by an exact local ledger entry; claims fail to pending."""
    try:
        snapshot = _json_object(review["artifact_snapshot_json"])
        if snapshot is None or _digest(snapshot) != review["artifact_sha256"] or snapshot.get("id") != review["artifact_id"]:
            return "pending", False, None
        latest = connection.execute(
            """SELECT MAX(artifact_version) FROM mission_artifact_reviews
               WHERE owner=? AND mission_id=? AND artifact_id=?""",
            (review["owner"], review["mission_id"], review["artifact_id"]),
        ).fetchone()[0]
        if latest == review["artifact_version"]:
            mission = connection.execute(
                "SELECT document_json FROM missions WHERE id=? AND owner=?",
                (review["mission_id"], review["owner"]),
            ).fetchone()
            mission_doc = _json_object(mission["document_json"]) if mission else None
            artifacts = mission_doc.get("artifacts", []) if mission_doc else []
            matching = [item for item in artifacts if isinstance(item, dict)
                        and item.get("id") == review["artifact_id"]]
            if len(matching) != 1 or _artifact_payload(matching[0]) != _artifact_payload(snapshot):
                return "pending", False, snapshot
        decisions = connection.execute(
            "SELECT * FROM mission_review_decisions WHERE review_id=? AND owner=? ORDER BY created_at, id",
            (review["id"], review["owner"]),
        ).fetchall()
        if review["state"] == "pending" and not decisions:
            if any(review[field] is not None for field in ("decision_reason", "decision_actor", "decided_at")):
                return "pending", False, None
            return "pending", True, snapshot
        if review["state"] not in DECISIONS or len(decisions) != 1:
            return "pending", False, snapshot
        decision = decisions[0]
        ledger_snapshot = _json_object(decision["snapshot_json"])
        if (
            decision["review_id"] != review["id"]
            or decision["mission_id"] != review["mission_id"]
            or decision["owner"] != review["owner"]
            or decision["artifact_id"] != review["artifact_id"]
            or decision["artifact_version"] != review["artifact_version"]
            or decision["artifact_sha256"] != review["artifact_sha256"]
            or decision["decision"] != review["state"]
            or decision["decision_reason"] != review["decision_reason"]
            or decision["actor"] != review["decision_actor"]
            or decision["created_at"] != review["decided_at"]
            or ledger_snapshot != snapshot
            or not decision["actor"]
            or not decision["idempotency_key"]
        ):
            return "pending", False, snapshot
        return decision["decision"], True, snapshot
    except (KeyError, TypeError, ValueError):
        return "pending", False, None


def canonical_artifact_state(connection, owner: str, mission_id: str, artifact: dict) -> tuple[str, bool]:
    rows = connection.execute(
        """SELECT * FROM mission_artifact_reviews
           WHERE owner=? AND mission_id=? AND artifact_id=?
           ORDER BY artifact_version DESC LIMIT 1""",
        (owner, mission_id, artifact.get("id")),
    ).fetchone()
    if rows is None:
        return "draft", False
    state, valid, snapshot = canonical_review_state(connection, rows)
    if not valid or snapshot is None or _artifact_payload(artifact) != _artifact_payload(snapshot):
        return "draft", False
    return ("draft" if state == "pending" else state), True


def knowledge_source_review(connection, knowledge):
    if _value(knowledge, "source_review_id"):
        return connection.execute(
            "SELECT * FROM mission_artifact_reviews WHERE id=? AND mission_id=? AND owner=?",
            (knowledge["source_review_id"], knowledge["mission_id"], knowledge["owner"]),
        ).fetchone()
    knowledge_id = _value(knowledge, "id", "")
    if not isinstance(knowledge_id, str) or not knowledge_id.startswith("knowledge_capture_"):
        return None
    artifact_id = "artifact_capture_" + knowledge_id.removeprefix("knowledge_capture_")
    return connection.execute(
        """SELECT * FROM mission_artifact_reviews
           WHERE mission_id=? AND owner=? AND artifact_id=?
           ORDER BY artifact_version DESC LIMIT 1""",
        (knowledge["mission_id"], knowledge["owner"], artifact_id),
    ).fetchone()


def canonical_knowledge_decision(connection, knowledge, decision=None) -> tuple[str, bool, object | None]:
    """Check knowledge ledger bindings and the approved artifact version before use."""
    if decision is None:
        decision = connection.execute(
            "SELECT * FROM mission_knowledge_decisions WHERE knowledge_id=? AND owner=?",
            (knowledge["id"], knowledge["owner"]),
        ).fetchone()
    if decision is None:
        return "staged", True, None
    try:
        if (
            decision["knowledge_id"] != knowledge["id"]
            or decision["owner"] != knowledge["owner"]
            or decision["mission_id"] != knowledge["mission_id"]
            or decision["domain_id"] != knowledge["domain_id"]
            or decision["knowledge_sha256"] != _sha_text(knowledge["content"])
            or decision["actor"] != knowledge["owner"]
            or not decision["idempotency_key"]
        ):
            return "quarantined", False, decision
        if knowledge["kind"] == "selected_original":
            source = connection.execute(
                "SELECT id FROM selected_synthetic_sources WHERE owner=? AND mission_id=? AND knowledge_id=?",
                (knowledge["owner"], knowledge["mission_id"], knowledge["id"]),
            ).fetchone()
            if source is None or not prove_source(
                connection, source["id"], knowledge["owner"], knowledge["mission_id"]
            ).trusted:
                return "quarantined", False, decision
        review = knowledge_source_review(connection, knowledge)
        if review is None:
            if decision["source_review_id"] is not None or decision["source_artifact_sha256"] is not None:
                return "quarantined", False, decision
        elif (
            decision["source_review_id"] != review["id"]
            or decision["source_artifact_sha256"] != review["artifact_sha256"]
        ):
            return "quarantined", False, decision
        elif decision["decision"] == "approved":
            state, valid, _ = canonical_review_state(connection, review)
            if not valid or state != "approved":
                return "quarantined", False, decision
        return decision["decision"], True, decision
    except (KeyError, TypeError, ValueError):
        return "quarantined", False, decision


def verified_source_for_knowledge(connection, knowledge, owner: str | None = None) -> bool:
    if _value(knowledge, "kind") != "selected_original":
        return True
    owner = owner or _value(knowledge, "owner")
    if not owner:
        return False
    source = connection.execute(
        "SELECT id FROM selected_synthetic_sources WHERE owner=? AND mission_id=? AND knowledge_id=?",
        (owner, _value(knowledge, "mission_id"), _value(knowledge, "id")),
    ).fetchone()
    return bool(source and prove_source(connection, source["id"], owner,
                                        _value(knowledge, "mission_id")).trusted)


def review_is_unverified_source(connection, owner: str, review_id: str) -> bool:
    target = connection.execute(
        "SELECT * FROM mission_artifact_reviews WHERE owner=? AND id=?",
        (owner, review_id),
    ).fetchone()
    if target is None:
        return False
    sources = connection.execute(
        """SELECT s.* FROM selected_synthetic_sources s
           JOIN mission_artifact_reviews base ON base.id=s.review_id AND base.owner=s.owner
           WHERE s.owner=? AND base.mission_id=? AND base.artifact_id=?""",
        (owner, target["mission_id"], target["artifact_id"]),
    ).fetchall()
    if sources and (target["artifact_version"] != 1 or any(
        not prove_source(connection, source["id"], owner, target["mission_id"]).trusted
        for source in sources
    )):
        return True
    snapshot = _json_object(target["artifact_snapshot_json"])
    refs = snapshot.get("source_refs", []) if snapshot else []
    for ref in refs if isinstance(refs, list) else []:
        if isinstance(ref, dict) and isinstance(ref.get("source_id"), str):
            prefix = "synthetic:selected:"
            if ref["source_id"].startswith(prefix) and not prove_source(
                connection, ref["source_id"][len(prefix):], owner, target["mission_id"]
            ).trusted:
                return True
    return False


def is_selected_source_artifact(connection, owner: str, review_id: str) -> bool:
    linked = connection.execute(
        """SELECT 1 FROM mission_artifact_reviews target
           JOIN mission_artifact_reviews base ON base.mission_id=target.mission_id
             AND base.artifact_id=target.artifact_id AND base.artifact_version=1
           JOIN selected_synthetic_sources s ON s.review_id=base.id AND s.owner=base.owner
           WHERE target.owner=? AND target.id=? LIMIT 1""",
        (owner, review_id),
    ).fetchone() is not None
    if linked:
        return True
    review = connection.execute(
        "SELECT artifact_snapshot_json FROM mission_artifact_reviews WHERE owner=? AND id=?",
        (owner, review_id),
    ).fetchone()
    snapshot = _json_object(review["artifact_snapshot_json"]) if review else None
    return _source_id_from_artifact(snapshot or {}) is not None


def _source_id_from_artifact(artifact: dict) -> str | None:
    refs = artifact.get("source_refs")
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("source_id"), str):
            prefix = "synthetic:selected:"
            if ref["source_id"].startswith(prefix):
                return ref["source_id"][len(prefix):]
    return None


def redact_mission_record(connection, record: dict) -> dict:
    mission = record.get("mission")
    if not isinstance(mission, dict):
        return record
    result = dict(record)
    owner = record.get("owner")
    mission_id = mission.get("id")
    safe_mission = dict(mission)
    safe_artifacts = []
    quarantined_artifact_ids = set()
    if owner and mission_id:
        linked_sources = connection.execute(
            """SELECT s.id, r.artifact_id FROM selected_synthetic_sources s
               LEFT JOIN mission_artifact_reviews r ON r.id=s.review_id AND r.owner=s.owner
               WHERE s.owner=? AND s.mission_id=?""",
            (owner, mission_id),
        ).fetchall()
        for linked in linked_sources:
            if not prove_source(connection, linked["id"], owner, mission_id).trusted and linked["artifact_id"]:
                quarantined_artifact_ids.add(linked["artifact_id"])
    for artifact in mission.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        safe = dict(artifact)
        state, state_proven = canonical_artifact_state(
            connection, owner, mission.get("id"), artifact
        ) if owner and mission_id else ("draft", False)
        safe["review_state"] = state
        if not state_proven or state == "draft":
            safe["reviewed_at"] = None
        source_id = _source_id_from_artifact(artifact)
        source_untrusted = bool(source_id and (
            not owner or not prove_source(connection, source_id, owner, mission_id).trusted
        ))
        if safe.get("id") in quarantined_artifact_ids or source_untrusted:
            safe["content"] = ""
            safe["content_withheld"] = True
            safe["source_state"] = "quarantined"
            safe["review_state"] = "draft"
            safe["reviewed_at"] = None
        safe_artifacts.append(safe)
    safe_mission["artifacts"] = safe_artifacts
    result["mission"] = safe_mission
    return result


def reconcile_legacy_selected_sources(store) -> int:
    """Reconcile only migration-marked legacy rows; quarantine broken current claims."""
    upgraded = 0
    with store.transaction() as connection:
        candidates = connection.execute(
            """SELECT c.source_id, c.owner, s.*
               FROM selected_source_reconciliation c
               JOIN selected_synthetic_sources s ON s.id=c.source_id AND s.owner=c.owner
               WHERE c.status='pending' ORDER BY c.source_id"""
        ).fetchall()
        candidate_keys = {(row["source_id"], row["owner"]) for row in candidates}
        for row in candidates:
            fixture = legacy_source_fixture(connection, row)
            if fixture is None:
                connection.execute(
                    "UPDATE selected_source_reconciliation SET status='quarantined', reason='proof_incomplete', evaluated_at=CURRENT_TIMESTAMP WHERE source_id=? AND owner=? AND status='pending'",
                    (row["source_id"], row["owner"]),
                )
                continue
            connection.execute(
                """UPDATE selected_synthetic_sources SET display_name=?, classification='synthetic_verified',
                   state='selected', fixture_id=?, catalog_id=?, catalog_version=?, fixture_sha256=?, provenance_json=?
                   WHERE id=? AND owner=? AND classification='unverified' AND state='quarantined'""",
                (fixture["display_name"], fixture["id"], CATALOG_ID, CATALOG_VERSION,
                 fixture["content_sha256"], _canonical_json(fixture["provenance"]),
                 row["source_id"], row["owner"]),
            )
            proof = prove_source(connection, row["source_id"], row["owner"])
            if proof.trusted:
                connection.execute(
                    "UPDATE selected_source_reconciliation SET status='reconciled', evaluated_at=CURRENT_TIMESTAMP WHERE source_id=? AND owner=? AND status='pending'",
                    (row["source_id"], row["owner"]),
                )
                upgraded += 1
            else:
                connection.execute(
                    "UPDATE selected_synthetic_sources SET classification='unverified', state='quarantined' WHERE id=? AND owner=?",
                    (row["source_id"], row["owner"]),
                )
                connection.execute(
                    "UPDATE selected_source_reconciliation SET status='quarantined', reason='proof_incomplete', evaluated_at=CURRENT_TIMESTAMP WHERE source_id=? AND owner=? AND status='pending'",
                    (row["source_id"], row["owner"]),
                )

        rows = connection.execute(
            "SELECT id, owner, mission_id FROM selected_synthetic_sources WHERE classification='synthetic_verified' OR state='selected'"
        ).fetchall()
        for row in rows:
            if (row["id"], row["owner"]) in candidate_keys:
                continue
            if not prove_source(connection, row["id"], row["owner"], row["mission_id"]).trusted:
                connection.execute(
                    "UPDATE selected_synthetic_sources SET classification='unverified', state='quarantined' WHERE id=? AND owner=?",
                    (row["id"], row["owner"]),
                )
    return upgraded
