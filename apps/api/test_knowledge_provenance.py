"""Positive provenance is required for every persisted knowledge origin."""

from __future__ import annotations

import sqlite3
import json

import pytest

from test_review_api import ORIGIN, client, create_and_run_step, login, mission_all_grants
from test_selected_source_api import _body, _headers


UNTRUSTED_BYTES = "UNTRUSTED_R6_AUDIT_KNOWLEDGE_BYTES"


def _item(client, knowledge_id: str) -> dict:
    response = client.get("/real/knowledge", headers={"origin": ORIGIN})
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["id"] == knowledge_id)


def test_selected_knowledge_detached_as_skill_derived_is_quarantined_everywhere(client):
    csrf = login(client)
    mission_all_grants(client, csrf)

    step, _ = create_and_run_step(client, csrf, "Prova positiva de conhecimento derivado")
    mission_id = step["mission"]["id"]
    knowledge_before = client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
    valid_derived = next(item for item in knowledge_before if item["kind"] == "skill_derived")
    assert valid_derived["content_withheld"] is False

    selected_response = client.post(
        f"/real/missions/{mission_id}/sources",
        headers=_headers(csrf),
        json=_body("tarefas-de-exemplo", "r61-exact-provenance-attack"),
    )
    assert selected_response.status_code == 201, selected_response.text
    source = selected_response.json()
    with sqlite3.connect(client.database_path) as connection:
        selected_knowledge_id = connection.execute(
            "SELECT knowledge_id FROM selected_synthetic_sources WHERE id=?", (source["id"],)
        ).fetchone()[0]
    selected_before = _item(client, selected_knowledge_id)
    assert selected_before["kind"] == "selected_original"
    assert selected_before["content_withheld"] is False

    with sqlite3.connect(client.database_path) as connection:
        connection.execute(
            "UPDATE selected_synthetic_sources SET knowledge_id=? WHERE id=?",
            (valid_derived["id"], source["id"]),
        )
        connection.execute(
            "UPDATE mission_knowledge SET kind='skill_derived', source_review_id=NULL, content=? WHERE id=?",
            (UNTRUSTED_BYTES, selected_knowledge_id),
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    leaked = _item(client, selected_knowledge_id)
    assert leaked["state"] == "quarantined"
    assert leaked["content"] == ""
    assert leaked["content_withheld"] is True
    assert leaked["content_sha256"] is None
    assert leaked.get("origin_verified") is False
    assert leaked.get("can_approve") is False
    assert UNTRUSTED_BYTES not in str(leaked)

    source_list = client.get(
        f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN}
    )
    assert source_list.status_code == 200
    selected_source = next(item for item in source_list.json()["items"] if item["id"] == source["id"])
    assert selected_source["selection_state"] == "quarantined"
    assert selected_source["classification"] == "unverified"
    assert UNTRUSTED_BYTES not in source_list.text

    mission = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
    assert mission.status_code == 200
    assert UNTRUSTED_BYTES not in mission.text
    review = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN})
    assert review.status_code == 200
    assert UNTRUSTED_BYTES not in review.text
    assert review.json()["content_withheld"] is True

    decision = client.post(
        f"/real/knowledge/{selected_knowledge_id}/decide",
        headers=_headers(csrf),
        json={
            "decision": "approved",
            "expected_content_sha256": _sha(UNTRUSTED_BYTES),
            "idempotency_key": "r61-untrusted-knowledge-approve",
        },
    )
    assert decision.status_code == 409
    context = client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN})
    assert context.status_code == 200
    assert context.json()["included"] == []
    assert UNTRUSTED_BYTES not in context.text

    current = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
    context_step = client.post(
        f"/real/missions/{mission_id}/transition",
        headers=_headers(csrf),
        json={
            "action": "run_next",
            "expected_revision": current["revision"],
            "idempotency_key": "r61-build-context-untrusted-knowledge",
        },
    )
    assert context_step.status_code == 200, context_step.text
    assert UNTRUSTED_BYTES not in context_step.text
    context_artifact = next(
        item for item in context_step.json()["mission"]["artifacts"]
        if item["kind"] == "context_bundle"
    )
    assert UNTRUSTED_BYTES not in context_artifact["content"]

    after_context = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
    report_step = client.post(
        f"/real/missions/{mission_id}/transition",
        headers=_headers(csrf),
        json={
            "action": "run_next",
            "expected_revision": after_context["revision"],
            "idempotency_key": "r61-complete-untrusted-knowledge-mission",
        },
    )
    assert report_step.status_code == 200, report_step.text
    assert report_step.json()["mission"]["status"] == "done"
    assert UNTRUSTED_BYTES not in report_step.text


def _sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _create_source(client, csrf: str, mission_id: str, fixture_id: str, key: str) -> tuple[dict, str]:
    response = client.post(
        f"/real/missions/{mission_id}/sources",
        headers=_headers(csrf),
        json=_body(fixture_id, key),
    )
    assert response.status_code == 201, response.text
    source = response.json()
    with sqlite3.connect(client.database_path) as connection:
        knowledge_id = connection.execute(
            "SELECT knowledge_id FROM selected_synthetic_sources WHERE id=?", (source["id"],)
        ).fetchone()[0]
    return source, knowledge_id


def _derived_record(client, csrf: str, title: str) -> tuple[dict, dict]:
    step, _ = create_and_run_step(client, csrf, title)
    mission = step["mission"]
    item = next(
        row for row in client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
        if row["mission_id"] == mission["id"] and row["kind"] == "skill_derived"
    )
    return mission, item


def _replace_mission_document(connection, mission_id: str, change) -> None:
    row = connection.execute("SELECT document_json FROM missions WHERE id=?", (mission_id,)).fetchone()
    document = json.loads(row[0])
    change(document)
    connection.execute(
        "UPDATE missions SET document_json=? WHERE id=?",
        (json.dumps(document, ensure_ascii=False), mission_id),
    )


KNOWLEDGE_TAMPERING_CASES = [
    "selected_to_skill_without_review_and_bytes",
    "selected_to_skill_with_review",
    "derived_to_selected",
    "derived_cross_mission",
    "derived_cross_owner",
    "producer_artifact_missing",
    "producer_artifact_from_other_mission",
    "execution_digest_changed",
    "knowledge_content_changed",
    "execution_missing",
    "execution_moved_to_other_mission",
    "unknown_kind",
    "null_kind_rejected_by_schema",
    "orphan_knowledge",
    "selected_relinked_to_other_valid_source",
    "source_relinked_to_derived_knowledge",
    "two_valid_sources_crossed",
    "four_fields_changed_together",
    "approved_state_without_provenance",
    "decision_ledger_from_other_knowledge",
]


def test_legitimate_skill_derived_knowledge_needs_approved_source_review(client):
    from test_knowledge_api import _headers as knowledge_headers

    csrf = login(client)
    mission_all_grants(client, csrf)
    mission, item = _derived_record(client, csrf, "R6.1 origem derivada legítima")
    assert item["origin_verified"] is True
    assert item["origin_type"] == "skill_derived"
    assert item["state"] == "staged"
    assert item["content_withheld"] is False
    assert item["can_approve"] is False
    assert item["source_review_id"]

    review = client.get(f"/real/reviews/{item['source_review_id']}", headers={"origin": ORIGIN}).json()
    assert review["state"] == "pending"
    approved_review = client.post(
        f"/real/reviews/{item['source_review_id']}/decide",
        headers=_headers(csrf),
        json={
            "decision": "approved",
            "expected_revision": review["revision"],
            "expected_artifact_sha256": review["artifact_sha256"],
            "idempotency_key": "r61-approve-derived-source-review",
        },
    )
    assert approved_review.status_code == 200, approved_review.text
    item = _item(client, item["id"])
    assert item["can_approve"] is True

    decision = client.post(
        f"/real/knowledge/{item['id']}/decide",
        headers=knowledge_headers(csrf),
        json={
            "decision": "approved",
            "expected_content_sha256": item["content_sha256"],
            "idempotency_key": "r61-approve-derived-knowledge",
        },
    )
    assert decision.status_code == 200, decision.text
    assert _item(client, item["id"])["state"] == "approved"
    context = client.get(
        f"/real/knowledge/context/{mission['id']}", headers={"origin": ORIGIN}
    )
    assert context.status_code == 200
    assert item["id"] in {row["knowledge_id"] for row in context.json()["included"]}


@pytest.mark.parametrize("case", KNOWLEDGE_TAMPERING_CASES)
def test_unproven_knowledge_tampering_matrix_fails_closed(client, case):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission, derived = _derived_record(client, csrf, f"R6.1 prova principal {case}")
    other_mission, other_derived = _derived_record(client, csrf, f"R6.1 prova alternativa {case}")
    first_source, selected_id = _create_source(
        client, csrf, mission["id"], "tarefas-de-exemplo", f"r61-matrix-a-{case}"
    )
    source_ids = [(first_source, selected_id)]
    if case in {"selected_relinked_to_other_valid_source", "two_valid_sources_crossed", "decision_ledger_from_other_knowledge"}:
        second_source, second_selected_id = _create_source(
            client, csrf, mission["id"], "resumo-de-demonstracao", f"r61-matrix-b-{case}"
        )
        source_ids.append((second_source, second_selected_id))

    target_id = selected_id if case in {
        "selected_to_skill_without_review_and_bytes",
        "selected_to_skill_with_review",
        "selected_relinked_to_other_valid_source",
        "source_relinked_to_derived_knowledge",
        "two_valid_sources_crossed",
    } else derived["id"]
    with sqlite3.connect(client.database_path) as connection:
        connection.row_factory = sqlite3.Row
        if case == "selected_to_skill_without_review_and_bytes":
            connection.execute(
                "UPDATE selected_synthetic_sources SET knowledge_id=? WHERE id=?",
                (derived["id"], first_source["id"]),
            )
            connection.execute(
                "UPDATE mission_knowledge SET kind='skill_derived', source_review_id=NULL, content=? WHERE id=?",
                (UNTRUSTED_BYTES, selected_id),
            )
        elif case == "selected_to_skill_with_review":
            connection.execute("UPDATE mission_knowledge SET kind='skill_derived' WHERE id=?", (selected_id,))
        elif case == "derived_to_selected":
            connection.execute("UPDATE mission_knowledge SET kind='selected_original' WHERE id=?", (derived["id"],))
        elif case == "derived_cross_mission":
            connection.execute("UPDATE mission_knowledge SET mission_id=? WHERE id=?", (other_mission["id"], derived["id"]))
        elif case == "derived_cross_owner":
            connection.execute("UPDATE mission_knowledge SET owner='owner_b' WHERE id=?", (derived["id"],))
        elif case == "producer_artifact_missing":
            _replace_mission_document(
                connection, mission["id"],
                lambda doc: doc.update(artifacts=[a for a in doc.get("artifacts", []) if not a.get("id", "").startswith("artifact_capture_")]),
            )
        elif case == "producer_artifact_from_other_mission":
            foreign = next(a for a in other_mission["artifacts"] if a.get("id", "").startswith("artifact_capture_"))
            _replace_mission_document(
                connection, mission["id"],
                lambda doc: doc.update(artifacts=[a for a in doc.get("artifacts", []) if not a.get("id", "").startswith("artifact_capture_")] + [foreign]),
            )
        elif case == "execution_digest_changed":
            connection.execute("UPDATE mission_executions SET input_digest=? WHERE mission_id=? AND task_id='task_capture'", ("0" * 64, mission["id"]))
        elif case == "knowledge_content_changed":
            connection.execute("UPDATE mission_knowledge SET content=? WHERE id=?", (UNTRUSTED_BYTES, derived["id"]))
        elif case == "execution_missing":
            connection.execute("DELETE FROM mission_executions WHERE mission_id=? AND task_id='task_capture'", (mission["id"],))
        elif case == "execution_moved_to_other_mission":
            connection.execute("UPDATE mission_executions SET mission_id=? WHERE mission_id=? AND task_id='task_capture'", (other_mission["id"], mission["id"]))
        elif case == "unknown_kind":
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE mission_knowledge SET kind='unrecognized_origin' WHERE id=?", (derived["id"],))
        elif case == "null_kind_rejected_by_schema":
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("UPDATE mission_knowledge SET kind=NULL WHERE id=?", (derived["id"],))
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE mission_knowledge SET kind='invalid_origin' WHERE id=?", (derived["id"],))
        elif case == "orphan_knowledge":
            connection.execute(
                """INSERT INTO mission_knowledge
                   (id, owner, mission_id, domain_id, state, content, skill_version, created_at, kind, source_review_id)
                   VALUES (?, ?, ?, ?, 'staged', ?, '1.0.0', ?, 'skill_derived', NULL)""",
                ("knowledge_orphan_r61", "owner", mission["id"], mission["domain_id"], UNTRUSTED_BYTES, derived["created_at"]),
            )
            target_id = "knowledge_orphan_r61"
        elif case == "selected_relinked_to_other_valid_source":
            connection.execute("UPDATE selected_synthetic_sources SET knowledge_id=? WHERE id=?", (source_ids[1][1], first_source["id"]))
        elif case == "source_relinked_to_derived_knowledge":
            connection.execute("UPDATE selected_synthetic_sources SET knowledge_id=? WHERE id=?", (derived["id"], first_source["id"]))
            target_id = derived["id"]
        elif case == "two_valid_sources_crossed":
            connection.execute("UPDATE selected_synthetic_sources SET knowledge_id=? WHERE id=?", (source_ids[1][1], source_ids[0][0]["id"]))
            connection.execute("UPDATE selected_synthetic_sources SET knowledge_id=? WHERE id=?", (source_ids[0][1], source_ids[1][0]["id"]))
        elif case == "four_fields_changed_together":
            connection.execute(
                "UPDATE mission_knowledge SET content=?, mission_id=?, skill_version=? WHERE id=?",
                (UNTRUSTED_BYTES, other_mission["id"], "99.0.0", derived["id"]),
            )
            _replace_mission_document(
                connection, mission["id"],
                lambda doc: doc.update(artifacts=[a for a in doc.get("artifacts", []) if not a.get("id", "").startswith("artifact_capture_")]),
            )
        elif case == "approved_state_without_provenance":
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE mission_knowledge SET state='approved', kind='unrecognized_origin' WHERE id=?", (derived["id"],))
        elif case == "decision_ledger_from_other_knowledge":
            second_source, second_id = source_ids[1]
            review = client.get(f"/real/reviews/{second_source['review_id']}", headers={"origin": ORIGIN}).json()
            review_decision = client.post(
                f"/real/reviews/{second_source['review_id']}/decide",
                headers=_headers(csrf),
                json={"decision": "approved", "expected_revision": review["revision"],
                      "expected_artifact_sha256": review["artifact_sha256"],
                      "idempotency_key": "r61-matrix-review-for-ledger"},
            )
            assert review_decision.status_code == 200, review_decision.text
            second_item = _item(client, second_id)
            accepted = client.post(
                f"/real/knowledge/{second_id}/decide", headers=_headers(csrf),
                json={"decision": "approved", "expected_content_sha256": second_item["content_sha256"],
                      "idempotency_key": "r61-matrix-source-ledger"},
            )
            assert accepted.status_code == 200, accepted.text
            ledger = connection.execute("SELECT * FROM mission_knowledge_decisions WHERE knowledge_id=?", (second_id,)).fetchone()
            columns = [key for key in ledger.keys()]
            values = dict(ledger)
            values.update(id="r61-cross-knowledge-ledger", knowledge_id=derived["id"], idempotency_key="r61-cross-knowledge-key")
            connection.execute(
                f"INSERT INTO mission_knowledge_decisions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                [values[column] for column in columns],
            )
        else:
            raise AssertionError(f"Caso de adulteração não implementado: {case}")

        row = connection.execute("SELECT * FROM mission_knowledge WHERE id=?", (target_id,)).fetchone()
        assert row is not None
        from source_admission import resolve_trusted_knowledge_projection
        assert resolve_trusted_knowledge_projection(connection, row, row["owner"]).trusted is False
        additional_ids = []
        if case == "selected_relinked_to_other_valid_source":
            additional_ids = [source_ids[1][1]]
        elif case == "source_relinked_to_derived_knowledge":
            additional_ids = [selected_id]
        elif case == "two_valid_sources_crossed":
            additional_ids = [source_ids[1][1]]
        for additional_id in additional_ids:
            additional = connection.execute(
                "SELECT * FROM mission_knowledge WHERE id=?", (additional_id,)
            ).fetchone()
            assert additional is not None
            assert resolve_trusted_knowledge_projection(
                connection, additional, additional["owner"],
            ).trusted is False
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    response = client.get("/real/knowledge", headers={"origin": ORIGIN})
    assert response.status_code == 200
    list_ids = [target_id]
    if case in {"selected_relinked_to_other_valid_source", "source_relinked_to_derived_knowledge", "two_valid_sources_crossed"}:
        list_ids.extend(additional_ids)
    listed_items = {row["id"]: row for row in response.json()["items"]}
    if case == "derived_cross_owner":
        assert target_id not in listed_items
    else:
        for list_id in list_ids:
            listed = listed_items.get(list_id)
            assert listed is not None
            assert listed["state"] == "quarantined"
            assert listed["content"] == ""
            assert listed["content_withheld"] is True
            assert listed["origin_verified"] is False
            assert listed["content_sha256"] is None
            assert listed["can_approve"] is False
            assert listed["can_use_context"] is False
            assert UNTRUSTED_BYTES not in json.dumps(listed, ensure_ascii=False)
