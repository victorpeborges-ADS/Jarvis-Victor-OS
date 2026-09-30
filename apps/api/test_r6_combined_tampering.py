"""Combined source-chain attacks for the R6 local G5 trust contract.

These probes cover inconsistent edits inside the supported TCB. A host
administrator who can fabricate every database record coherently is explicitly
outside G5's authenticity guarantee; a separate passing probe documents that
boundary at the end of this module.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3

import pytest

from mission_repository import _sha
from source_catalog import fixture_for
from test_knowledge_api import _headers
from test_review_api import ORIGIN, client, create_and_run_step, login, mission_all_grants
from test_r5_trusted_state import _approved_source
from test_selected_source_api import _mission


CASES = [
    "owner_and_artifact_ref",       # Exact R5 auditor finding.
    "owner_and_valid_mission",
    "mission_and_artifact_ref",
    "domain_and_artifact_ref",
    "knowledge_review_link",
    "review_artifact_and_snapshot",
    "fixture_and_recalculated_hash",
    "catalog_version_and_valid_bytes",
    "snapshot_from_second_source",
    "crossed_owner",
    "crossed_mission_source",
    "mixed_valid_sources",
    "orphan_source_review",
    "orphan_knowledge",
    "orphan_review",
    "orphan_snapshot",
    "ledger_other_artifact",
    "ledger_other_mission",
    "knowledge_kind_and_links_detached",
]


def _other_mission(client, csrf: str, suffix: str) -> str:
    response = client.post("/real/missions", headers=_headers(csrf), json={
        "title": f"Missão alternativa R6 {suffix}", "domain_id": "dom_synthetic_a",
        "idempotency_key": f"r6-other-mission-{suffix}",
    })
    assert response.status_code == 201, response.text
    return response.json()["mission"]["id"]


def _approved_source_in_mission(client, csrf: str, mission_id: str, fixture_id: str, suffix: str):
    response = client.post(
        f"/real/missions/{mission_id}/sources", headers=_headers(csrf),
        json={"fixture_id": fixture_id, "idempotency_key": f"r6-second-source-{suffix}"},
    )
    assert response.status_code == 201, response.text
    source = response.json()
    review = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN}).json()
    decided = client.post(f"/real/reviews/{source['review_id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_revision": review["revision"],
        "expected_artifact_sha256": review["artifact_sha256"],
        "idempotency_key": f"r6-second-review-{suffix}",
    })
    assert decided.status_code == 200, decided.text
    knowledge = next(item for item in client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
                     if item["source_review_id"] == source["review_id"])
    accepted = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
        "idempotency_key": f"r6-second-knowledge-{suffix}",
    })
    assert accepted.status_code == 200, accepted.text
    return source, review, knowledge


def _edit_artifact_ref(connection, mission_id: str, artifact_id: str, source_id: str) -> None:
    row = connection.execute("SELECT document_json FROM missions WHERE id=?", (mission_id,)).fetchone()
    document = json.loads(row[0])
    artifact = next(item for item in document["artifacts"] if item["id"] == artifact_id)
    artifact["source_refs"][0]["source_id"] = f"synthetic:selected:{source_id}"
    connection.execute("UPDATE missions SET document_json=? WHERE id=?",
                       (json.dumps(document, ensure_ascii=False), mission_id))


def _insert_extra_ledger(connection, source, *, mission_id: str | None = None,
                          artifact_id: str | None = None) -> None:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM mission_review_decisions WHERE review_id=? AND owner=?",
        (source["review_id"], "owner"),
    ).fetchone()
    assert row is not None
    connection.execute(
        """INSERT INTO mission_review_decisions
           (id, review_id, mission_id, owner, artifact_id, artifact_version,
            artifact_sha256, decision, decision_reason, actor, idempotency_key,
            snapshot_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (f"r6-forged-extra-{source['id']}", row["review_id"],
         mission_id or row["mission_id"], row["owner"], artifact_id or row["artifact_id"],
         row["artifact_version"], row["artifact_sha256"], row["decision"],
         row["decision_reason"], row["actor"], f"r6-extra-{source['id']}",
         row["snapshot_json"], row["created_at"]),
    )


@pytest.mark.parametrize("case", CASES)
def test_combined_source_tampering_fails_closed_across_surfaces(client, case):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id, source, initial_review, knowledge = _approved_source(client, csrf)
    fixture = fixture_for("tarefas-de-exemplo")
    assert fixture is not None

    other_mission_id = None
    other_source = None
    if case in {
        "owner_and_valid_mission", "mission_and_artifact_ref", "knowledge_review_link",
        "snapshot_from_second_source", "crossed_mission_source", "mixed_valid_sources",
        "ledger_other_mission",
    }:
        other_mission_id = _other_mission(client, csrf, case)
    if case in {"knowledge_review_link", "snapshot_from_second_source", "crossed_mission_source", "mixed_valid_sources"}:
        other_source, _, _ = _approved_source_in_mission(
            client, csrf, other_mission_id, "resumo-de-demonstracao", case,
        )

    with sqlite3.connect(client.database_path) as connection:
        if case == "owner_and_artifact_ref":
            _edit_artifact_ref(connection, mission_id, initial_review["artifact_id"], "missing-r6-source")
            connection.execute("UPDATE selected_synthetic_sources SET owner='owner_b' WHERE id=?", (source["id"],))
        elif case == "owner_and_valid_mission":
            connection.execute(
                "UPDATE selected_synthetic_sources SET owner='owner_b', mission_id=? WHERE id=?",
                (other_mission_id, source["id"]),
            )
        elif case == "mission_and_artifact_ref":
            connection.execute("UPDATE selected_synthetic_sources SET mission_id=? WHERE id=?",
                               (other_mission_id, source["id"]))
            _edit_artifact_ref(connection, mission_id, initial_review["artifact_id"], "missing-r6-source")
        elif case == "domain_and_artifact_ref":
            connection.execute("UPDATE selected_synthetic_sources SET domain_id='dom_synthetic_b' WHERE id=?",
                               (source["id"],))
            _edit_artifact_ref(connection, mission_id, initial_review["artifact_id"], "missing-r6-source")
        elif case == "knowledge_review_link":
            connection.execute("UPDATE mission_knowledge SET source_review_id=? WHERE id=?",
                               (other_source["review_id"] if other_source else "rev_other", knowledge["id"]))
        elif case == "knowledge_kind_and_links_detached":
            connection.execute("UPDATE mission_knowledge SET kind='skill_derived', source_review_id='review-r6-other' WHERE id=?",
                               (knowledge["id"],))
            connection.execute("UPDATE selected_synthetic_sources SET knowledge_id='knowledge-r6-orphan' WHERE id=?",
                               (source["id"],))
        elif case == "review_artifact_and_snapshot":
            raw = connection.execute(
                "SELECT artifact_snapshot_json FROM mission_artifact_reviews WHERE id=?",
                (source["review_id"],),
            ).fetchone()[0]
            snapshot = json.loads(raw)
            snapshot["id"] = "artifact-r6-coherent-snapshot-only"
            connection.execute(
                "UPDATE mission_artifact_reviews SET artifact_id=?, artifact_snapshot_json=?, artifact_sha256=? WHERE id=?",
                (snapshot["id"], json.dumps(snapshot, ensure_ascii=False), _sha(snapshot), source["review_id"]),
            )
        elif case == "fixture_and_recalculated_hash":
            fixture_digest = hashlib.sha256(fixture["content"].encode("utf-8")).hexdigest()
            connection.execute(
                "UPDATE selected_synthetic_sources SET fixture_id='fixture-r6-forged', fixture_sha256=?, content_sha256=? WHERE id=?",
                (fixture_digest, fixture_digest, source["id"]),
            )
        elif case == "catalog_version_and_valid_bytes":
            connection.execute("UPDATE selected_synthetic_sources SET catalog_version='999.0.0' WHERE id=?",
                               (source["id"],))
        elif case == "snapshot_from_second_source":
            second_snapshot = connection.execute(
                "SELECT artifact_snapshot_json FROM mission_artifact_reviews WHERE id=?",
                (other_source["review_id"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE mission_artifact_reviews SET artifact_snapshot_json=?, artifact_sha256=? WHERE id=?",
                (second_snapshot, _sha(json.loads(second_snapshot)), source["review_id"]),
            )
        elif case == "crossed_owner":
            connection.execute("UPDATE selected_synthetic_sources SET owner='owner_b' WHERE id=?", (source["id"],))
        elif case == "crossed_mission_source":
            connection.execute("UPDATE selected_synthetic_sources SET mission_id=? WHERE id=?",
                               (other_mission_id, source["id"]))
            _edit_artifact_ref(connection, mission_id, initial_review["artifact_id"], other_source["id"])
        elif case == "mixed_valid_sources":
            _edit_artifact_ref(connection, mission_id, initial_review["artifact_id"], other_source["id"])
        elif case == "orphan_source_review":
            connection.execute("UPDATE selected_synthetic_sources SET review_id='review-r6-orphan' WHERE id=?",
                               (source["id"],))
        elif case == "orphan_knowledge":
            connection.execute("DELETE FROM mission_knowledge WHERE id=?", (knowledge["id"],))
        elif case == "orphan_review":
            connection.execute("DELETE FROM mission_artifact_reviews WHERE id=?", (source["review_id"],))
        elif case == "orphan_snapshot":
            connection.execute("UPDATE mission_artifact_reviews SET artifact_snapshot_json=NULL WHERE id=?",
                               (source["review_id"],))
        elif case == "ledger_other_artifact":
            _insert_extra_ledger(connection, source, artifact_id="artifact-r6-other")
        elif case == "ledger_other_mission":
            _insert_extra_ledger(connection, source, mission_id=other_mission_id)
        else:
            raise AssertionError(case)

    mission_response = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
    assert mission_response.status_code == 200, mission_response.text
    mission_payload = mission_response.json()
    artifact = next(item for item in mission_payload["mission"]["artifacts"]
                    if item["id"] == initial_review["artifact_id"])
    assert artifact["content"] == ""
    assert artifact["content_withheld"] is True
    assert fixture["content"] not in mission_response.text

    sources = client.get(f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN})
    assert sources.status_code == 200
    assert fixture["content"] not in sources.text
    assert all(item.get("classification") != "synthetic_verified"
               for item in sources.json()["items"])
    assert all(item.get("content_withheld") is True for item in sources.json()["items"])

    review = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN})
    if case == "orphan_review":
        assert review.status_code == 404
    else:
        assert review.status_code == 200, review.text
        assert review.json()["state"] == "pending"
        assert review.json()["content_withheld"] is True
        assert review.json()["artifact"]["content"] == ""
        assert review.json()["history"] == []
        assert fixture["content"] not in review.text

    review_list = client.get(f"/real/missions/{mission_id}/reviews", headers={"origin": ORIGIN})
    assert review_list.status_code == 200
    assert not any(item["id"] == source["review_id"] and item["state"] == "approved"
                   for item in review_list.json()["items"])

    knowledge_list = client.get("/real/knowledge", headers={"origin": ORIGIN})
    assert knowledge_list.status_code == 200
    selected = next((item for item in knowledge_list.json()["items"] if item["id"] == knowledge["id"]), None)
    if case == "orphan_knowledge":
        assert selected is None
    else:
        assert selected is not None
        assert selected["content"] == ""
        assert selected["state"] == "quarantined"
        assert selected["content_sha256"] is None
    assert fixture["content"] not in knowledge_list.text

    if case != "orphan_knowledge":
        decision = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json={
            "decision": "approved", "expected_content_sha256": fixture["content_sha256"],
            "idempotency_key": f"r6-deny-knowledge-{case}",
        })
        assert decision.status_code in {404, 409}
    context = client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN})
    assert context.status_code == 200
    assert context.json()["included"] == []
    assert fixture["content"] not in context.text

    if case != "orphan_review":
        refused = client.post(f"/real/reviews/{source['review_id']}/decide", headers=_headers(csrf), json={
            "decision": "approved", "expected_revision": 3,
            "expected_artifact_sha256": initial_review["artifact_sha256"],
            "idempotency_key": f"r6-deny-review-{case}",
        })
        assert refused.status_code in {404, 422}

    # The context skill must consume only the fail-closed assembly, then allow
    # deterministic mission completion without echoing the selected fixture.
    expected = mission_payload["revision"]
    for index in range(3):
        run = client.post(f"/real/missions/{mission_id}/transition", headers=_headers(csrf), json={
            "action": "run_next", "expected_revision": expected,
            "idempotency_key": f"r6-run-{case}-{index}",
        })
        assert run.status_code == 200, run.text
        expected = run.json()["revision"]
        assert fixture["content"] not in run.text
        assert all(item.get("content") != fixture["content"]
                   for item in run.json()["mission"]["artifacts"])
    assert run.json()["mission"]["status"] == "done"


def test_coherent_sqlite_admin_fabrication_is_documented_outside_g5_authenticity(client):
    """A fully coherent database fabrication is outside the local G5 guarantee.

    This is a boundary demonstration, not an application failure: the test
    asserts that relational checks cannot authenticate the human event when
    the writer can fabricate every field that the application itself stores.
    """
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "R6 limite do escritor SQLite")
    decided_at = "2026-09-30T12:00:00+00:00"
    with sqlite3.connect(client.database_path) as connection:
        connection.row_factory = sqlite3.Row
        review = connection.execute("SELECT * FROM mission_artifact_reviews WHERE id=?", (review_id,)).fetchone()
        snapshot = review["artifact_snapshot_json"]
        connection.execute(
            "UPDATE mission_artifact_reviews SET state='approved', decision_actor='owner', decided_at=?, revision=revision+1 WHERE id=?",
            (decided_at, review_id),
        )
        connection.execute(
            """INSERT INTO mission_review_decisions
               (id, review_id, mission_id, owner, artifact_id, artifact_version,
                artifact_sha256, decision, decision_reason, actor, idempotency_key,
                snapshot_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', NULL, ?, ?, ?, ?)""",
            ("r6-admin-fabricated-decision", review_id, review["mission_id"], review["owner"],
             review["artifact_id"], review["artifact_version"], review["artifact_sha256"],
             "owner", "r6-admin-fabricated-key", snapshot, decided_at),
        )
    response = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN})
    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert response.json()["decision_state_proven"] is True
