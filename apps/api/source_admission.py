"""Canonical source proof, legacy quarantine, and safe output helpers."""

from __future__ import annotations

import hashlib
import json

from source_catalog import CATALOG_ID, CATALOG_VERSION, FIXTURES


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def source_matches_fixture(source, fixture: dict, content: str) -> bool:
    try:
        provenance = json.loads(source["provenance_json"])
        expected_provenance = dict(fixture["provenance"])
        return (
            source["classification"] == "synthetic_verified"
            and source["state"] == "selected"
            and source["fixture_id"] == fixture["id"]
            and source["catalog_id"] == CATALOG_ID
            and source["catalog_version"] == CATALOG_VERSION
            and source["fixture_sha256"] == fixture["content_sha256"]
            and source["content_sha256"] == fixture["content_sha256"] == _sha(content)
            and source["byte_count"] == len(content.encode("utf-8"))
            and source["display_name"] == fixture["display_name"]
            and provenance == expected_provenance
            and content == fixture["content"]
        )
    except (KeyError, TypeError, ValueError):
        return False


def verified_source_for_knowledge(connection, knowledge, owner: str | None = None) -> bool:
    if knowledge["kind"] != "selected_original":
        return True
    owner = owner or knowledge["owner"]
    source = connection.execute(
        """SELECT * FROM selected_synthetic_sources
           WHERE owner=? AND mission_id=? AND knowledge_id=?""",
        (owner, knowledge["mission_id"], knowledge["id"]),
    ).fetchone()
    if source is None or knowledge["source_review_id"] != source["review_id"]:
        return False
    fixture = FIXTURES.get(source["fixture_id"])
    if fixture is None or not source_matches_fixture(source, fixture, knowledge["content"]):
        return False
    review = connection.execute(
        """SELECT artifact_id, artifact_sha256, artifact_snapshot_json
           FROM mission_artifact_reviews WHERE id=? AND owner=? AND mission_id=?""",
        (source["review_id"], source["owner"], source["mission_id"]),
    ).fetchone()
    if review is None:
        return False
    try:
        snapshot = json.loads(review["artifact_snapshot_json"])
        digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        return (
            snapshot.get("id") == review["artifact_id"]
            and snapshot.get("content") == fixture["content"]
            and snapshot.get("input_digest") == fixture["content_sha256"]
            and review["artifact_sha256"] == digest
            and any(ref.get("source_id") == f"synthetic:selected:{source['id']}"
                    for ref in snapshot.get("source_refs", []))
        )
    except (TypeError, ValueError, AttributeError):
        return False


def review_is_unverified_source(connection, owner: str, review_id: str) -> bool:
    target = connection.execute(
        "SELECT mission_id, artifact_id, artifact_version FROM mission_artifact_reviews WHERE owner=? AND id=?",
        (owner, review_id),
    ).fetchone()
    if target is None:
        return False
    row = connection.execute(
        """SELECT s.classification, s.state, k.id, k.owner, k.mission_id,
                  k.source_review_id, k.content, k.kind, s.review_id AS selected_review_id
           FROM selected_synthetic_sources s
           JOIN mission_knowledge k ON k.id=s.knowledge_id AND k.owner=s.owner
           JOIN mission_artifact_reviews base ON base.id=s.review_id AND base.owner=s.owner
           WHERE s.owner=? AND base.mission_id=? AND base.artifact_id=?""",
        (owner, target["mission_id"], target["artifact_id"]),
    ).fetchone()
    if row is None:
        return False
    return target["artifact_version"] != 1 or target["artifact_id"] is None or (
        row["classification"] != "synthetic_verified"
        or row["state"] != "selected"
        or not verified_source_for_knowledge(connection, row, owner)
    )


def is_selected_source_artifact(connection, owner: str, review_id: str) -> bool:
    return connection.execute(
        """SELECT 1 FROM mission_artifact_reviews target
           JOIN mission_artifact_reviews base ON base.mission_id=target.mission_id
             AND base.artifact_id=target.artifact_id AND base.artifact_version=1
           JOIN selected_synthetic_sources s ON s.review_id=base.id AND s.owner=base.owner
           WHERE target.owner=? AND target.id=? LIMIT 1""",
        (owner, review_id),
    ).fetchone() is not None


def redact_mission_record(connection, record: dict) -> dict:
    mission = record.get("mission")
    if not isinstance(mission, dict):
        return record
    result = dict(record)
    safe_mission = dict(mission)
    safe_artifacts = []
    rows = connection.execute(
        """SELECT r.artifact_id, s.classification, s.state, s.fixture_id, k.id, k.owner,
                  k.mission_id, k.source_review_id, k.content, k.kind
           FROM selected_synthetic_sources s
           JOIN mission_artifact_reviews r ON r.id=s.review_id AND r.owner=s.owner
           JOIN mission_knowledge k ON k.id=s.knowledge_id AND k.owner=s.owner
           WHERE s.owner=? AND s.mission_id=?""",
        (record.get("owner"), mission.get("id")),
    ).fetchall()
    quarantined_ids = {row["artifact_id"] for row in rows if (
        row["classification"] != "synthetic_verified" or row["state"] != "selected"
        or not verified_source_for_knowledge(connection, row, record.get("owner"))
    )}
    current_artifacts = {item.get("id"): item for item in mission.get("artifacts", [])}
    for row in rows:
        fixture = FIXTURES.get(row["fixture_id"])
        current = current_artifacts.get(row["artifact_id"])
        if fixture is None or current is None or current.get("content") != fixture["content"]:
            quarantined_ids.add(row["artifact_id"])
    for artifact in mission.get("artifacts", []):
        safe_artifact = dict(artifact)
        if safe_artifact.get("id") in quarantined_ids:
            safe_artifact["content"] = ""
            safe_artifact["content_withheld"] = True
        safe_artifacts.append(safe_artifact)
    safe_mission["artifacts"] = safe_artifacts
    result["mission"] = safe_mission
    return result


def reconcile_legacy_selected_sources(store) -> int:
    """Upgrade only byte-exact historical records with linked snapshot proof."""
    upgraded = 0
    with store.transaction() as connection:
        rows = connection.execute(
            """SELECT s.*, k.content, k.kind, k.source_review_id,
                      r.artifact_id, r.artifact_sha256, r.artifact_snapshot_json
               FROM selected_synthetic_sources s
               LEFT JOIN mission_knowledge k ON k.id=s.knowledge_id AND k.owner=s.owner
               LEFT JOIN mission_artifact_reviews r ON r.id=s.review_id AND r.owner=s.owner
               WHERE s.classification='unverified'"""
        ).fetchall()
        for source in rows:
            for fixture in FIXTURES.values():
                if not (
                    source["content"] == fixture["content"]
                    and source["content_sha256"] == fixture["content_sha256"]
                    and source["byte_count"] == len(fixture["content"].encode("utf-8"))
                    and source["kind"] == "selected_original"
                    and source["source_review_id"] == source["review_id"]
                    and source["artifact_id"] is not None
                ):
                    continue
                try:
                    snapshot = json.loads(source["artifact_snapshot_json"])
                    snapshot_sha = hashlib.sha256(json.dumps(
                        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()).hexdigest()
                    linked = (
                        snapshot.get("id") == source["artifact_id"]
                        and snapshot.get("content") == fixture["content"]
                        and snapshot.get("input_digest") == fixture["content_sha256"]
                        and source["artifact_sha256"] == snapshot_sha
                        and any(ref.get("source_id") == f"synthetic:selected:{source['id']}"
                                for ref in snapshot.get("source_refs", []))
                    )
                except (TypeError, ValueError, AttributeError):
                    linked = False
                if not linked:
                    continue
                connection.execute(
                    """UPDATE selected_synthetic_sources SET display_name=?, classification='synthetic_verified',
                       state='selected', fixture_id=?, catalog_id=?, catalog_version=?, fixture_sha256=?, provenance_json=?
                       WHERE id=? AND owner=? AND classification='unverified'""",
                    (fixture["display_name"], fixture["id"], CATALOG_ID, CATALOG_VERSION,
                     fixture["content_sha256"], json.dumps(fixture["provenance"], ensure_ascii=False,
                                                            sort_keys=True, separators=(",", ":")),
                     source["id"], source["owner"]),
                )
                upgraded += 1
                break
    return upgraded
