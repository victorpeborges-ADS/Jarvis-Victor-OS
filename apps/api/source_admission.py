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


@dataclass(frozen=True)
class TrustedSourceProjection:
    """One projection for selected-source trust across every read surface.

    ``applicable`` distinguishes ordinary artifacts from records that claim or
    are relationally connected to a selected source. A connected-but-invalid
    source is applicable and untrusted, so callers must withhold its content.
    """

    applicable: bool
    trusted: bool
    proof: SourceProof | None = None


@dataclass(frozen=True)
class TrustedKnowledgeProjection:
    """Positive proof for one persisted knowledge origin.

    ``kind`` is only a stored claim. ``trusted`` is true only when either the
    selected-source chain or the deterministic skill execution, artifact,
    event, and review chain is reconstructed in full.
    """

    trusted: bool
    origin_type: str | None = None
    source_review: object | None = None
    source_review_state: str | None = None
    artifact: dict | None = None
    execution: object | None = None


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
    selected_refs = [ref for ref in refs if isinstance(ref, dict)
                     and isinstance(ref.get("source_id"), str)
                     and ref["source_id"].startswith("synthetic:selected:")] if isinstance(refs, list) else []
    if (len(selected_refs) != 1 or selected_refs[0].get("source_id") != expected_ref
            or selected_refs[0].get("domain_id") != source["domain_id"]):
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


def _selected_source_ref_ids(artifact: dict | None) -> list[str]:
    if not isinstance(artifact, dict):
        return []
    refs = artifact.get("source_refs")
    if not isinstance(refs, list):
        return []
    prefix = "synthetic:selected:"
    return [ref["source_id"][len(prefix):] for ref in refs
            if isinstance(ref, dict) and isinstance(ref.get("source_id"), str)
            and ref["source_id"].startswith(prefix)]


def resolve_trusted_source_projection(
    connection,
    owner: str,
    mission_id: str | None = None,
    *,
    source_id: str | None = None,
    artifact: dict | None = None,
    knowledge=None,
    review_id: str | None = None,
) -> TrustedSourceProjection:
    """Resolve a single source identity and the full canonical relation chain.

    Candidate discovery is deliberately owner-unscoped: a mismatched owner or
    relation must be detected and withheld, not disappear from the query and
    leave a source-backed artifact looking ordinary. Values discovered here
    are never returned by the public projection unless every edge is proved.
    """
    candidates: dict[str, object] = {}
    evidence_artifacts: list[dict] = [artifact] if isinstance(artifact, dict) else []
    applicable = source_id is not None

    def add_rows(rows) -> None:
        nonlocal applicable
        for row in rows:
            candidates[row["id"]] = row
            applicable = True

    def add_by_id(candidate_id: str) -> None:
        row = connection.execute(
            "SELECT * FROM selected_synthetic_sources WHERE id=?", (candidate_id,),
        ).fetchone()
        if row is not None:
            candidates[row["id"]] = row

    def add_artifact_relations(item: dict, item_mission_id: str | None) -> None:
        nonlocal applicable
        ref_ids = _selected_source_ref_ids(item)
        if item.get("skill_id") == "selected-synthetic-file" or ref_ids:
            applicable = True
        for ref_id in ref_ids:
            add_by_id(ref_id)
        item_id = item.get("id")
        if item_mission_id and isinstance(item_id, str):
            add_rows(connection.execute(
                """SELECT DISTINCT s.* FROM selected_synthetic_sources s
                   JOIN mission_artifact_reviews r ON r.id=s.review_id
                   WHERE r.mission_id=? AND r.artifact_id=?""",
                (item_mission_id, item_id),
            ).fetchall())

    if source_id is not None:
        add_by_id(source_id)
    for item in evidence_artifacts:
        add_artifact_relations(item, mission_id)

    if knowledge is not None:
        if _value(knowledge, "kind") == "selected_original":
            applicable = True
        knowledge_id = _value(knowledge, "id")
        if isinstance(knowledge_id, str):
            add_rows(connection.execute(
                "SELECT * FROM selected_synthetic_sources WHERE knowledge_id=?",
                (knowledge_id,),
            ).fetchall())
            decision_links = connection.execute(
                "SELECT source_review_id FROM mission_knowledge_decisions WHERE knowledge_id=?",
                (knowledge_id,),
            ).fetchall()
            for link in decision_links:
                linked_review_id = link["source_review_id"]
                if linked_review_id:
                    add_rows(connection.execute(
                        "SELECT * FROM selected_synthetic_sources WHERE review_id=?",
                        (linked_review_id,),
                    ).fetchall())
        linked_review_id = _value(knowledge, "source_review_id")
        if isinstance(linked_review_id, str):
            add_rows(connection.execute(
                "SELECT * FROM selected_synthetic_sources WHERE review_id=?",
                (linked_review_id,),
            ).fetchall())
        knowledge_content = _value(knowledge, "content")
        knowledge_mission = _value(knowledge, "mission_id")
        if isinstance(knowledge_content, str) and isinstance(knowledge_mission, str):
            add_rows(connection.execute(
                "SELECT * FROM selected_synthetic_sources WHERE mission_id=? AND content_sha256=?",
                (knowledge_mission, _sha_text(knowledge_content)),
            ).fetchall())

    target_review = None
    if review_id is not None:
        target_review = connection.execute(
            "SELECT * FROM mission_artifact_reviews WHERE id=?", (review_id,),
        ).fetchone()
        add_rows(connection.execute(
            "SELECT * FROM selected_synthetic_sources WHERE review_id=?", (review_id,),
        ).fetchall())
        if target_review is not None:
            mission_id = mission_id or target_review["mission_id"]
            snapshot = _json_object(target_review["artifact_snapshot_json"])
            if snapshot is not None:
                evidence_artifacts.append(snapshot)
                add_artifact_relations(snapshot, target_review["mission_id"])
            base_sources = connection.execute(
                """SELECT DISTINCT s.* FROM selected_synthetic_sources s
                   JOIN mission_artifact_reviews base ON base.id=s.review_id
                   WHERE base.mission_id=? AND base.artifact_id=?""",
                (target_review["mission_id"], target_review["artifact_id"]),
            ).fetchall()
            add_rows(base_sources)
            mission_row = connection.execute(
                "SELECT document_json FROM missions WHERE id=?",
                (target_review["mission_id"],),
            ).fetchone()
            mission_doc = _json_object(mission_row["document_json"]) if mission_row else None
            artifacts = mission_doc.get("artifacts", []) if mission_doc else []
            current = next((item for item in artifacts if isinstance(item, dict)
                            and item.get("id") == target_review["artifact_id"]), None)
            if current is not None:
                evidence_artifacts.append(current)
                add_artifact_relations(current, target_review["mission_id"])

    if not applicable:
        return TrustedSourceProjection(applicable=False, trusted=False)
    if len(candidates) != 1:
        return TrustedSourceProjection(applicable=True, trusted=False)

    selected_id, selected_row = next(iter(candidates.items()))
    if source_id is not None and selected_id != source_id:
        return TrustedSourceProjection(applicable=True, trusted=False)
    mission_id = mission_id or _value(selected_row, "mission_id")
    proof = prove_source(connection, selected_id, owner, mission_id)
    if not proof.trusted or proof.review is None:
        return TrustedSourceProjection(applicable=True, trusted=False, proof=proof)

    # Every selected-source marker in every observed copy must identify the
    # same row. This catches a stale snapshot/current document split as well
    # as the combined owner + artifact-ref corruption from the R5 audit.
    for item in evidence_artifacts:
        refs = _selected_source_ref_ids(item)
        if item.get("skill_id") == "selected-synthetic-file" or refs:
            if refs != [selected_id]:
                return TrustedSourceProjection(applicable=True, trusted=False, proof=proof)
            if (proof.artifact is None or item.get("id") != proof.artifact.get("id")
                    or _artifact_payload(item) != _artifact_payload(proof.artifact)):
                return TrustedSourceProjection(applicable=True, trusted=False, proof=proof)

    _, review_valid, _ = canonical_review_state(connection, proof.review)
    if not review_valid:
        return TrustedSourceProjection(applicable=True, trusted=False, proof=proof)
    if knowledge is not None and (
        proof.knowledge is None
        or _value(knowledge, "id") != proof.knowledge["id"]
        or _value(knowledge, "owner") != owner
        or _value(knowledge, "mission_id") != mission_id
        or _value(knowledge, "domain_id") != proof.knowledge["domain_id"]
        or _value(knowledge, "source_review_id") != proof.review["id"]
        or _value(knowledge, "content") != proof.fixture["content"]
    ):
        return TrustedSourceProjection(applicable=True, trusted=False, proof=proof)
    if target_review is not None and (
        proof.review["id"] != target_review["id"]
        or proof.review["owner"] != owner
        or proof.review["mission_id"] != target_review["mission_id"]
        or proof.review["domain_id"] != target_review["domain_id"]
        or proof.review["artifact_id"] != target_review["artifact_id"]
        or proof.review["artifact_version"] != target_review["artifact_version"]
        or proof.review["artifact_sha256"] != target_review["artifact_sha256"]
    ):
        return TrustedSourceProjection(applicable=True, trusted=False, proof=proof)
    return TrustedSourceProjection(applicable=True, trusted=True, proof=proof)


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


def _skill_execution_digest(title: str, task_id: str) -> str:
    return hashlib.sha256(f"{task_id}:{title}".encode("utf-8")).hexdigest()


def _positive_skill_derived_knowledge(connection, knowledge, owner: str) -> TrustedKnowledgeProjection:
    """Reconstruct the only current server flow that creates skill-derived knowledge.

    The knowledge table has no direct execution foreign key. The application
    already records enough canonical evidence to prove its origin: deterministic
    knowledge/artifact IDs and bytes, the committed capture execution, the exact
    artifact snapshot, and the two execution-correlated server events. Legacy
    rows missing any of these links remain stored but are not exposed as trusted.
    """
    from synthetic_skill import capture_and_classify

    knowledge_id = _value(knowledge, "id")
    mission_id = _value(knowledge, "mission_id")
    domain_id = _value(knowledge, "domain_id")
    created_at = _value(knowledge, "created_at")
    if (
        _value(knowledge, "owner") != owner
        or _value(knowledge, "kind") != "skill_derived"
        or _value(knowledge, "source_review_id") is not None
        or not isinstance(knowledge_id, str)
        or not isinstance(mission_id, str)
        or not isinstance(domain_id, str)
        or not isinstance(_value(knowledge, "content"), str)
        or not isinstance(created_at, str)
    ):
        return TrustedKnowledgeProjection(trusted=False)

    # Any discovered selected-source edge makes this a conflicting lineage;
    # a skill-derived claim cannot erase a selected-source proof.
    source_projection = resolve_trusted_source_projection(
        connection, owner, mission_id, knowledge=knowledge,
    )
    if source_projection.applicable:
        return TrustedKnowledgeProjection(trusted=False)

    mission_row = connection.execute(
        "SELECT id, owner, domain_id, document_json FROM missions WHERE id=?",
        (mission_id,),
    ).fetchone()
    mission = _json_object(mission_row["document_json"]) if mission_row is not None else None
    if (
        mission_row is None
        or mission is None
        or mission_row["id"] != mission_id
        or mission_row["owner"] != owner
        or mission_row["domain_id"] != domain_id
        or mission.get("id") != mission_id
        or mission.get("domain_id") != domain_id
        or not isinstance(mission.get("title"), str)
    ):
        return TrustedKnowledgeProjection(trusted=False)

    tasks = mission.get("tasks")
    if not isinstance(tasks, list):
        return TrustedKnowledgeProjection(trusted=False)
    capture_tasks = [task for task in tasks if isinstance(task, dict) and task.get("id") == "task_capture"]
    if len(capture_tasks) != 1:
        return TrustedKnowledgeProjection(trusted=False)
    task = capture_tasks[0]
    attempt = task.get("attempt")
    if task.get("status") != "done" or not isinstance(attempt, int) or attempt < 1:
        return TrustedKnowledgeProjection(trusted=False)

    input_digest = _skill_execution_digest(mission["title"], "task_capture")
    expected_execution_id = f"exec_{mission_id[-12:]}_task_capture_{attempt}"
    executions = connection.execute(
        """SELECT * FROM mission_executions
           WHERE id=? AND mission_id=? AND owner=? AND task_id=? AND phase='committed'
             AND attempt=? AND skill_id=? AND skill_version=? AND input_digest=?
             AND committed_at=?""",
        (expected_execution_id, mission_id, owner, "task_capture", attempt,
         "capture-and-classify", "1.0.0", input_digest, created_at),
    ).fetchall()
    if len(executions) != 1:
        return TrustedKnowledgeProjection(trusted=False)
    execution = executions[0]

    expected_artifact, expected_knowledge = capture_and_classify(
        mission["title"], domain_id, created_at, mission_id,
    )
    expected_artifact["skill_id"] = "capture-and-classify"
    expected_artifact["input_digest"] = input_digest
    if (
        knowledge_id != expected_knowledge.get("id")
        or _value(knowledge, "content") != expected_knowledge.get("content")
        or domain_id != expected_knowledge.get("domain_id")
        or _value(knowledge, "skill_version") != expected_knowledge.get("skill_version")
    ):
        return TrustedKnowledgeProjection(trusted=False)

    artifacts = mission.get("artifacts")
    if not isinstance(artifacts, list):
        return TrustedKnowledgeProjection(trusted=False)
    matching_artifacts = [
        artifact for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("id") == expected_artifact.get("id")
    ]
    if len(matching_artifacts) != 1 or _artifact_payload(matching_artifacts[0]) != _artifact_payload(expected_artifact):
        return TrustedKnowledgeProjection(trusted=False)
    artifact = matching_artifacts[0]

    events = mission.get("events")
    if not isinstance(events, list):
        return TrustedKnowledgeProjection(trusted=False)
    for event_type, stable_suffix in (("task_completed", "completed"), ("artifact_created", "artifact")):
        stable_key = f"{expected_execution_id}:{stable_suffix}"
        document_events = [
            event for event in events
            if isinstance(event, dict) and event.get("idempotency_key") == stable_key
        ]
        database_events = connection.execute(
            """SELECT * FROM mission_events
               WHERE idempotency_key=? AND mission_id=? AND owner=?""",
            (stable_key, mission_id, owner),
        ).fetchall()
        if len(document_events) != 1 or len(database_events) != 1:
            return TrustedKnowledgeProjection(trusted=False)
        document_event = document_events[0]
        database_event = database_events[0]
        if (
            document_event.get("type") != event_type
            or document_event.get("task_id") != "task_capture"
            or document_event.get("created_at") != created_at
            or database_event["id"] != document_event.get("id")
            or database_event["event_type"] != event_type
            or database_event["actor"] != owner
            or database_event["correlation_id"] != stable_key
            or database_event["created_at"] != created_at
        ):
            return TrustedKnowledgeProjection(trusted=False)

    review = knowledge_source_review(connection, knowledge)
    if (
        review is None
        or review["id"] != f"rev_{expected_artifact['id']}_1"
        or review["owner"] != owner
        or review["mission_id"] != mission_id
        or review["artifact_id"] != expected_artifact["id"]
        or review["artifact_version"] != 1
    ):
        return TrustedKnowledgeProjection(trusted=False)
    review_state, review_valid, _ = canonical_review_state(connection, review)
    artifact_state, artifact_valid = canonical_artifact_state(
        connection, owner, mission_id, artifact,
    )
    projected_review_state = "draft" if review_state == "pending" else review_state
    if not review_valid or not artifact_valid or projected_review_state != artifact_state:
        return TrustedKnowledgeProjection(trusted=False)
    return TrustedKnowledgeProjection(
        trusted=True,
        origin_type="skill_derived",
        source_review=review,
        source_review_state=review_state,
        artifact=artifact,
        execution=execution,
    )


def resolve_trusted_knowledge_projection(
    connection, knowledge, owner: str | None = None,
) -> TrustedKnowledgeProjection:
    """Project positive provenance for every persisted knowledge row.

    Unknown kinds and disconnected rows are untrusted. A stored ``kind`` only
    selects which proof to attempt; it never grants trust itself.
    """
    owner = owner or _value(knowledge, "owner")
    if not isinstance(owner, str) or _value(knowledge, "owner") != owner:
        return TrustedKnowledgeProjection(trusted=False)
    kind = _value(knowledge, "kind")
    if kind == "selected_original":
        projection = resolve_trusted_source_projection(
            connection, owner, _value(knowledge, "mission_id"), knowledge=knowledge,
        )
        proof = projection.proof
        if (
            not projection.applicable
            or not projection.trusted
            or proof is None
            or proof.knowledge is None
            or proof.review is None
            or proof.artifact is None
        ):
            return TrustedKnowledgeProjection(trusted=False)
        state, valid, _ = canonical_review_state(connection, proof.review)
        if not valid:
            return TrustedKnowledgeProjection(trusted=False)
        return TrustedKnowledgeProjection(
            trusted=True,
            origin_type="selected_original",
            source_review=proof.review,
            source_review_state=state,
            artifact=proof.artifact,
        )
    if kind == "skill_derived":
        return _positive_skill_derived_knowledge(connection, knowledge, owner)
    return TrustedKnowledgeProjection(trusted=False)


def canonical_knowledge_decision(connection, knowledge, decision=None) -> tuple[str, bool, object | None]:
    """Check positive origin proof and the ledger before use or display."""
    projection = resolve_trusted_knowledge_projection(connection, knowledge)
    if not projection.trusted or projection.source_review is None:
        return "quarantined", False, None
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
        review = projection.source_review
        if (
            decision["source_review_id"] != review["id"]
            or decision["source_artifact_sha256"] != review["artifact_sha256"]
        ):
            return "quarantined", False, decision
        if decision["decision"] == "approved":
            state, valid, _ = canonical_review_state(connection, review)
            if not valid or state != "approved":
                return "quarantined", False, decision
        return decision["decision"], True, decision
    except (KeyError, TypeError, ValueError):
        return "quarantined", False, decision


def verified_source_for_knowledge(connection, knowledge, owner: str | None = None) -> bool:
    """Compatibility predicate backed only by positive origin evidence."""
    return resolve_trusted_knowledge_projection(connection, knowledge, owner).trusted


def review_is_unverified_source(connection, owner: str, review_id: str) -> bool:
    projection = resolve_trusted_source_projection(connection, owner, review_id=review_id)
    return projection.applicable and not projection.trusted


def is_selected_source_artifact(connection, owner: str, review_id: str) -> bool:
    return resolve_trusted_source_projection(
        connection, owner, review_id=review_id,
    ).applicable


def redact_untrusted_source_artifact(artifact: dict) -> dict:
    """Keep only a safe placeholder when a selected-source chain is incomplete."""
    safe = dict(artifact)
    safe["content"] = ""
    safe["content_withheld"] = True
    safe["title"] = "Fonte retida para verificação"
    safe["source_refs"] = []
    safe["review_state"] = "draft"
    safe["reviewed_at"] = None
    safe["source_state"] = "quarantined"
    for key in ("input_digest", "fixture_id", "catalog_id", "catalog_version",
                "fixture_sha256", "content_sha256", "provenance", "classification",
                "selection_state", "skill_id"):
        safe.pop(key, None)
    return safe


def redact_mission_record(connection, record: dict) -> dict:
    mission = record.get("mission")
    if not isinstance(mission, dict):
        return record
    result = dict(record)
    owner = record.get("owner")
    mission_id = mission.get("id")
    safe_mission = dict(mission)
    safe_artifacts = []
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
        projection = resolve_trusted_source_projection(
            connection, owner or "", mission_id, artifact=artifact,
        )
        if projection.applicable and not projection.trusted:
            safe = redact_untrusted_source_artifact(safe)
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
