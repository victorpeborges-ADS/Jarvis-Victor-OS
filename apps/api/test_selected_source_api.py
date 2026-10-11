"""Selected synthetic files stay staged through both human review gates."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from shutil import copyfile

from fastapi.testclient import TestClient

from backup_recovery import create_backup, restore_backup
from local_security import Grant, put_grant_for_tests, put_session_for_tests
from memory_store import MIGRATIONS_DIR, SQLiteMemoryStore
from mission_repository import _sha
from source_admission import reconcile_legacy_selected_sources
from source_catalog import fixture_for
from test_review_api import ORIGIN, client, login, mission_all_grants


def _headers(csrf):
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def _mission(client, csrf):
    response = client.post("/real/missions", headers=_headers(csrf), json={
        "title": "Missão com fonte escolhida", "domain_id": "dom_synthetic_a",
        "idempotency_key": "source-mission-create",
    })
    assert response.status_code == 201, response.text
    return response.json()["mission"]["id"]


def _body(fixture_id="tarefas-de-exemplo", idempotency_key="selected-source-key"):
    return {"fixture_id": fixture_id, "idempotency_key": idempotency_key}


def _fixture_content():
    return "Tarefas de exemplo\n- Revisar rótulos.\n- Conferir estados.\nPróximo passo: registrar resultado sintético.\n"


def test_selected_source_needs_two_decisions_and_survives_backup(client, tmp_path):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    body = _body()
    posted = client.post(path, headers=_headers(csrf), json=body)
    assert posted.status_code == 201, posted.text
    source = posted.json()
    assert source["replayed"] is False
    assert client.post(path, headers=_headers(csrf), json=body).json()["replayed"] is True
    source_status = client.get(path, headers={"origin": ORIGIN}).json()["items"]
    assert len(source_status) == 1
    assert source_status[0]["selection_state"] == "selected"
    assert source_status[0]["classification"] == "synthetic_verified"
    assert source_status[0]["fixture_id"] == "tarefas-de-exemplo"
    assert source_status[0]["provenance"]["kind"] == "curated_server_fixture"
    assert source_status[0]["artifact_review_state"] == "pending"
    assert source_status[0]["knowledge_state"] == "staged"
    knowledge = next(item for item in client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
                     if item["kind"] == "selected_original")
    assert knowledge["state"] == "staged"
    context_path = f"/real/knowledge/context/{mission_id}"
    assert client.get(context_path, headers={"origin": ORIGIN}).json()["included"] == []
    decision = {"decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
                "idempotency_key": "selected-knowledge-approval"}
    assert client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=decision).status_code == 409
    review = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN}).json()
    assert review["artifact"]["content"] == _fixture_content()
    accepted = client.post(f"/real/reviews/{source['review_id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_revision": 1,
        "expected_artifact_sha256": review["artifact_sha256"],
        "idempotency_key": "selected-artifact-approval",
    })
    assert accepted.status_code == 200, accepted.text
    assert client.get(context_path, headers={"origin": ORIGIN}).json()["included"] == []
    approved = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=decision)
    assert approved.status_code == 200, approved.text
    included = client.get(context_path, headers={"origin": ORIGIN}).json()["included"]
    assert len(included) == 1 and included[0]["content"] == _fixture_content()
    assert included[0]["source_review_id"] == source["review_id"]
    final_status = client.get(path, headers={"origin": ORIGIN}).json()["items"][0]
    assert final_status["artifact_review_state"] == "approved"
    assert final_status["knowledge_state"] == "approved"
    archive = create_backup(client.database_path, tmp_path / "backups", "senha-sintetica-arquivo-selecionado")
    restored = restore_backup(archive, tmp_path / "restore", "senha-sintetica-arquivo-selecionado")
    with sqlite3.connect(restored) as con:
        assert con.execute("SELECT COUNT(*) FROM selected_synthetic_sources").fetchone()[0] == 1
        persisted = con.execute("SELECT classification, state, fixture_id, catalog_version FROM selected_synthetic_sources").fetchone()
        assert persisted == ("synthetic_verified", "selected", "tarefas-de-exemplo", "1.0.0")
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    SQLiteMemoryStore(restored).initialize()


def test_selected_source_rejects_client_owned_content_metadata_and_unknown_fixtures(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    good = _body()
    attacks = [
        {"fixture_id": "unknown-text", "idempotency_key": "unknown-fixture-key", "confirm_synthetic": True,
         "content": "Synthetic-looking but not curated."},
        {**good, "content": _fixture_content() + "extra bytes"},
        {**good, "content": "modified known fixture"},
        {**good, "display_name": "tarefas-de-exemplo.md"},
        {**good, "expected_content_sha256": "0" * 64},
        {**good, "classification": "synthetic_verified"},
        {**good, "classification": "synthetic_test_only"},
    ]
    for attack in attacks:
        response = client.post(path, headers=_headers(csrf), json=attack)
        assert response.status_code == 422, response.text
        assert "Synthetic-looking" not in response.text
        assert "extra bytes" not in response.text
    assert client.get(path, headers={"origin": ORIGIN}).json()["items"] == []
    assert client.post(path, headers=_headers(csrf), json=good).status_code == 201
    assert client.post(path, headers=_headers(csrf), json=_body("checklist-sintetico", good["idempotency_key"])).status_code == 409
    assert client.post(path, headers=_headers(csrf), json=_body("nao-existe", "unknown-fixture-2")).status_code == 422
    assert len(client.get(path, headers={"origin": ORIGIN}).json()["items"]) == 1


def test_selected_source_rejects_revoked_write_and_other_owner(client):
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    other_token = "selected-source-other-owner"
    put_session_for_tests(other_token, "other_owner", "other-owner-csrf")
    put_grant_for_tests(Grant(
        id="other-source-write", principal="other_owner", connector="mission_sim",
        resource_ids=frozenset({"mission:write"}), domain_ids=frozenset({"dom_synthetic_a"}),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    with TestClient(client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50994)) as other:
        other.cookies.set("jarvis_session", other_token)
        assert other.post(path, headers=_headers("other-owner-csrf"), json=_body()).status_code == 404
        assert other.get(path, headers={"origin": ORIGIN}).status_code == 404
    revoked = client.post(f"/real/grants/{grants['write']}/revoke", headers=_headers(csrf), json={})
    assert revoked.status_code == 200, revoked.text
    assert client.post(path, headers=_headers(csrf), json=_body()).status_code == 403
    assert client.get(path, headers={"origin": ORIGIN}).json()["items"] == []


def test_concurrent_identical_selection_creates_one_artifact(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, path, headers=_headers(csrf), json=_body()) for _ in range(2)]
        responses = [future.result() for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 201]
    assert sorted(response.json()["replayed"] for response in responses) == [False, True]
    assert len(client.get(path, headers={"origin": ORIGIN}).json()["items"]) == 1
    with sqlite3.connect(client.database_path) as con:
        assert con.execute("SELECT COUNT(*) FROM mission_knowledge WHERE kind='selected_original'").fetchone()[0] == 1


def test_selected_original_cannot_diverge_from_approved_artifact_snapshot(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    posted = client.post(path, headers=_headers(csrf), json=_body()).json()
    review = client.get(f"/real/reviews/{posted['review_id']}", headers={"origin": ORIGIN}).json()
    approved = client.post(f"/real/reviews/{posted['review_id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_revision": 1,
        "expected_artifact_sha256": review["artifact_sha256"],
        "idempotency_key": "approve-original-integrity",
    })
    assert approved.status_code == 200, approved.text
    knowledge = next(item for item in client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
                     if item["kind"] == "selected_original")
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE mission_knowledge SET content='texto divergente' WHERE id=?", (knowledge["id"],))
    decision = {"decision": "approved", "expected_content_sha256": hashlib.sha256(b"texto divergente").hexdigest(),
                "idempotency_key": "approve-divergent-original"}
    refused = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=decision)
    assert refused.status_code == 409
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE mission_knowledge SET content=? WHERE id=?", (_fixture_content(), knowledge["id"]))
    decision["expected_content_sha256"] = knowledge["content_sha256"]
    decision["idempotency_key"] = "approve-matching-original"
    assert client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=decision).status_code == 200
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE mission_knowledge SET content='texto divergente' WHERE id=?", (knowledge["id"],))
    bundle = client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN}).json()
    assert bundle["included"] == []
    assert bundle["omitted"][0]["reason"] == "fonte_em_quarentena"


def test_selected_fixture_review_cannot_be_revised_into_unverified_content(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    source = client.post(f"/real/missions/{mission_id}/sources", headers=_headers(csrf), json=_body()).json()
    detail = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN}).json()
    changes_requested = client.post(f"/real/reviews/{source['review_id']}/decide", headers=_headers(csrf), json={
        "decision": "changes_requested", "expected_revision": 1,
        "expected_artifact_sha256": detail["artifact_sha256"],
        "idempotency_key": "fixture-request-change", "reason": "Conteúdo precisa de ajuste.",
    })
    assert changes_requested.status_code == 200, changes_requested.text
    changed_text = "Tentativa de substituir o texto curado por conteúdo arbitrário."
    revise = client.post(f"/real/reviews/{source['review_id']}/revise", headers=_headers(csrf), json={
        "new_content": changed_text, "idempotency_key": "fixture-arbitrary-revision",
    })
    assert revise.status_code == 422
    assert changed_text not in revise.text
    queue = client.get(f"/real/reviews?domain_id=dom_synthetic_a", headers={"origin": ORIGIN}).json()["items"]
    assert not any(item["mission_id"] == mission_id and item["artifact_version"] > 1 for item in queue)
    persisted = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN}).json()
    assert persisted["artifact"]["content"] == _fixture_content()


def test_r4_postchange_unknown_content_probe_is_refused_without_echo_or_partial_write(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    content = "Synthetic-looking text that is not a server catalog fixture.\n"
    body = {
        "fixture_id": "unknown-fixture",
        "display_name": "nota-ficticia.md",
        "content": content,
        "expected_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "idempotency_key": "prechange-unknown-source",
        "confirm_synthetic": True,
        "classification": "synthetic_verified",
    }
    response = client.post(
        f"/real/missions/{mission_id}/sources", headers=_headers(csrf), json=body,
    )
    assert response.status_code == 422
    assert content not in response.text
    assert client.get(f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN}).json()["items"] == []
    with sqlite3.connect(client.database_path) as con:
        assert con.execute("SELECT COUNT(*) FROM mission_knowledge WHERE mission_id=?", (mission_id,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM selected_synthetic_sources WHERE mission_id=?", (mission_id,)).fetchone()[0] == 0


def test_catalog_is_server_owned_versioned_and_does_not_return_fixture_content(client):
    csrf = login(client)
    response = client.get("/real/missions/source-catalog/fixtures", headers={"origin": ORIGIN})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["catalog_id"] == "jarvis.synthetic_sources"
    assert body["catalog_version"] == "1.0.0"
    assert len(body["items"]) == 3
    assert all(item["classification"] == "synthetic_verified" for item in body["items"])
    assert all("content" not in item and item["provenance"]["kind"] == "curated_server_fixture"
               for item in body["items"])
    first = fixture_for("tarefas-de-exemplo")
    assert first is not None
    assert hashlib.sha256(first["content"].encode()).hexdigest() == first["content_sha256"]


def test_source_insert_failure_rolls_back_artifact_knowledge_and_source(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    with sqlite3.connect(client.database_path) as con:
        before = con.execute("SELECT revision, document_json FROM missions WHERE id=?", (mission_id,)).fetchone()
        con.execute("""CREATE TRIGGER refuse_selected_source BEFORE INSERT ON selected_synthetic_sources
                       BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
    response = client.post(f"/real/missions/{mission_id}/sources", headers=_headers(csrf), json=_body())
    assert response.status_code == 503
    assert "synthetic failure" not in response.text
    with sqlite3.connect(client.database_path) as con:
        after = con.execute("SELECT revision, document_json FROM missions WHERE id=?", (mission_id,)).fetchone()
        assert after == before
        assert con.execute("SELECT COUNT(*) FROM selected_synthetic_sources WHERE mission_id=?", (mission_id,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM mission_knowledge WHERE mission_id=? AND kind='selected_original'", (mission_id,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM mission_artifact_reviews WHERE mission_id=? AND artifact_id LIKE 'artifact_selected_%'", (mission_id,)).fetchone()[0] == 0


def test_migration_preserves_unknown_sources_and_reconciles_only_byte_exact_fixture(tmp_path):
    old_dir = tmp_path / "migrations-0013"
    old_dir.mkdir()
    for migration in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if migration.stem not in {
            "0014_curated_source_admission",
            "0015_selected_source_reconciliation",
            "0016_local_captures",
        }:
            copyfile(migration, old_dir / migration.name)
    db_path = tmp_path / "private" / "legacy.sqlite3"
    old_store = SQLiteMemoryStore(db_path, migrations_dir=old_dir)
    old_store.initialize()
    owner = "legacy-owner"
    mission_id = "mission_legacy_source_r4"
    now = "2026-09-26T00:00:00+00:00"
    fixture = fixture_for("tarefas-de-exemplo")
    assert fixture is not None
    records = [
        ("source_legacy_exact", "knowledge_legacy_exact", "review_legacy_exact",
         "artifact_selected_legacy_exact", fixture["display_name"], fixture["content"]),
        ("source_legacy_unknown", "knowledge_legacy_unknown", "review_legacy_unknown",
         "artifact_selected_legacy_unknown", "nota-antiga.md", "Texto antigo sem catálogo.\n"),
    ]
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("""INSERT INTO missions(id, owner, domain_id, status, revision, document_json, dataset, created_at, updated_at)
                       VALUES (?, ?, 'dom_synthetic_a', 'pending', 1, ?, 'api_synthetic', ?, ?)""",
                    (mission_id, owner, json.dumps({"id": mission_id, "domain_id": "dom_synthetic_a", "artifacts": []}), now, now))
        for source_id, knowledge_id, review_id, artifact_id, display_name, content in records:
            digest = hashlib.sha256(content.encode()).hexdigest()
            artifact = {
                "id": artifact_id, "kind": "evidence",
                "title": f"Fonte sintética selecionada: {display_name}" if display_name == fixture["display_name"] else f"Fonte: {display_name}",
                "content": content, "skill_id": "selected-synthetic-file", "skill_version": "1.0.0",
                "input_digest": digest, "review_state": "draft", "reviewed_at": None,
                "source_refs": [{"source_id": f"synthetic:selected:{source_id}", "domain_id": "dom_synthetic_a"}],
                "created_at": now,
            }
            artifact_json = json.dumps(artifact, ensure_ascii=False)
            artifact_sha = _sha(artifact)
            con.execute("""INSERT INTO mission_artifact_reviews
                           (id, mission_id, owner, artifact_id, artifact_version, artifact_sha256,
                            domain_id, state, revision, created_at, updated_at, artifact_snapshot_json)
                           VALUES (?, ?, ?, ?, 1, ?, 'dom_synthetic_a', 'pending', 1, ?, ?, ?)""",
                        (review_id, mission_id, owner, artifact_id, artifact_sha, now, now, artifact_json))
            con.execute("""INSERT INTO mission_knowledge
                           (id, owner, mission_id, domain_id, state, content, skill_version, created_at, kind, source_review_id)
                           VALUES (?, ?, ?, 'dom_synthetic_a', 'staged', ?, '1.0.0', ?, 'selected_original', ?)""",
                        (knowledge_id, owner, mission_id, content, now, review_id))
            con.execute("""INSERT INTO selected_synthetic_sources
                           (id, owner, mission_id, domain_id, display_name, content_sha256, review_id,
                            knowledge_id, idempotency_key, byte_count, classification, state, selected_at)
                           VALUES (?, ?, ?, 'dom_synthetic_a', ?, ?, ?, ?, ?, ?, 'synthetic_test_only', 'selected', ?)""",
                        (source_id, owner, mission_id, display_name, digest, review_id, knowledge_id,
                         f"legacy-{source_id}", len(content.encode()), now))
            current = json.loads(con.execute("SELECT document_json FROM missions WHERE id=?", (mission_id,)).fetchone()[0])
            current.setdefault("artifacts", []).append(artifact)
            con.execute("UPDATE missions SET document_json=? WHERE id=? AND owner=?",
                        (json.dumps(current, ensure_ascii=False), mission_id, owner))
    store = SQLiteMemoryStore(db_path)
    store.initialize()
    with store.transaction() as connection:
        before = connection.execute("SELECT COUNT(*) FROM selected_synthetic_sources").fetchone()[0]
        quarantined = connection.execute("""SELECT COUNT(*) FROM selected_synthetic_sources
                                            WHERE classification='unverified' AND state='quarantined'""").fetchone()[0]
    assert before == quarantined == 2
    assert reconcile_legacy_selected_sources(store) == 1
    with store.transaction() as connection:
        exact = connection.execute("SELECT * FROM selected_synthetic_sources WHERE id='source_legacy_exact'").fetchone()
        unknown = connection.execute("SELECT * FROM selected_synthetic_sources WHERE id='source_legacy_unknown'").fetchone()
        decisions = connection.execute("SELECT COUNT(*) FROM mission_knowledge_decisions").fetchone()[0]
    assert exact["classification"] == "synthetic_verified" and exact["state"] == "selected"
    assert exact["fixture_id"] == "tarefas-de-exemplo"
    assert exact["display_name"] == fixture["display_name"]
    assert unknown["classification"] == "unverified" and unknown["state"] == "quarantined"
    assert unknown["fixture_id"] is None
    assert decisions == 0


def test_unverified_legacy_source_is_quarantined_from_reads_reviews_and_context(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    source = client.post(path, headers=_headers(csrf), json=_body()).json()
    with sqlite3.connect(client.database_path) as con:
        con.execute("""UPDATE selected_synthetic_sources
                        SET classification='unverified', state='quarantined', fixture_id=NULL,
                            catalog_id=NULL, catalog_version=NULL, fixture_sha256=NULL, provenance_json=NULL
                        WHERE id=?""", (source["id"],))
    listed = client.get(path, headers={"origin": ORIGIN}).json()["items"][0]
    assert listed["classification"] == "unverified"
    assert listed["selection_state"] == "quarantined"
    knowledge_response = client.get("/real/knowledge", headers={"origin": ORIGIN}).json()
    knowledge = next(item for item in knowledge_response["items"] if item["kind"] == "selected_original")
    assert knowledge["state"] == "quarantined"
    assert knowledge["content"] == ""
    assert knowledge["content_withheld"] is True
    assert client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN}).json()["included"] == []
    review = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN}).json()
    assert review["content_withheld"] is True
    assert review["artifact"]["content"] == ""
    mission = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()["mission"]
    assert next(item for item in mission["artifacts"] if item["id"] == review["artifact_id"])["content"] == ""
    decision = {"decision": "approved", "expected_content_sha256": hashlib.sha256(_fixture_content().encode()).hexdigest(),
                "idempotency_key": "quarantined-knowledge-approval"}
    assert client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=decision).status_code == 409
    decision_review = client.post(f"/real/reviews/{source['review_id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_revision": 1,
        "expected_artifact_sha256": review["artifact_sha256"], "idempotency_key": "quarantined-review-approval",
    })
    assert decision_review.status_code == 422


def test_verified_fixture_full_mission_journey_finishes_after_separate_approvals(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    transition_path = f"/real/missions/{mission_id}/transition"
    headers = _headers(csrf)
    first = client.post(transition_path, headers=headers, json={
        "action": "run_next", "expected_revision": 1, "idempotency_key": "journey-capture-step",
    })
    assert first.status_code == 200, first.text

    source = client.post(f"/real/missions/{mission_id}/sources", headers=headers, json=_body(
        idempotency_key="journey-selected-source",
    ))
    assert source.status_code == 201, source.text
    selected = source.json()
    review = client.get(f"/real/reviews/{selected['review_id']}", headers={"origin": ORIGIN}).json()
    approved_artifact = client.post(f"/real/reviews/{selected['review_id']}/decide", headers=headers, json={
        "decision": "approved", "expected_revision": 1,
        "expected_artifact_sha256": review["artifact_sha256"],
        "idempotency_key": "journey-source-review-approval",
    })
    assert approved_artifact.status_code == 200, approved_artifact.text
    knowledge = next(item for item in client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
                     if item["kind"] == "selected_original")
    approved_knowledge = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=headers, json={
        "decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
        "idempotency_key": "journey-knowledge-approval",
    })
    assert approved_knowledge.status_code == 200, approved_knowledge.text

    for _ in range(4):
        current = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
        mission = current["mission"]
        if mission["status"] == "done":
            break
        response = client.post(transition_path, headers=headers, json={
            "action": "run_next", "expected_revision": current["revision"],
            "idempotency_key": f"journey-run-{current['revision']}",
        })
        assert response.status_code == 200, response.text
    else:
        raise AssertionError("a missão não concluiu em três etapas")
    mission = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()["mission"]
    context_artifact = next(item for item in mission["artifacts"] if item["kind"] == "context_bundle")
    assert _fixture_content() in context_artifact["content"]
    assert context_artifact["source_refs"][0]["source_id"].startswith("synthetic:knowledge:")
    assert next(item for item in mission["tasks"] if item["id"] == "task_report")["status"] == "done"
    final_sources = client.get(f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN}).json()["items"]
    assert final_sources[0]["artifact_review_state"] == "approved"
    assert final_sources[0]["knowledge_state"] == "approved"
