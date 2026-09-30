"""Adversarial probes for R5 source proofs and imported review claims."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backup_recovery import create_backup, restore_backup
from local_security import Grant, put_grant_for_tests, put_session_for_tests, reset_state
from main import create_app
from memory_store import SQLiteMemoryStore
from mission_repository import _sha
from server_config import LocalServerConfig
from source_admission import prove_source, reconcile_legacy_selected_sources
from source_catalog import fixture_for
from test_review_api import ORIGIN, client, create_and_run_step, login, mission_all_grants
from test_selected_source_api import _body, _headers, _mission


def _approved_source(client, csrf):
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    source_response = client.post(path, headers=_headers(csrf), json=_body())
    assert source_response.status_code == 201, source_response.text
    source = source_response.json()
    review = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN}).json()
    approved = client.post(f"/real/reviews/{source['review_id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_revision": 1,
        "expected_artifact_sha256": review["artifact_sha256"],
        "idempotency_key": f"r5-review-{source['id']}",
    })
    assert approved.status_code == 200, approved.text
    knowledge = next(item for item in client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
                     if item["kind"] == "selected_original")
    accepted = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
        "idempotency_key": f"r5-knowledge-{source['id']}",
    })
    assert accepted.status_code == 200, accepted.text
    source["knowledge_id"] = knowledge["id"]
    return mission_id, source, review, knowledge


def _tamper_source(client, source, mission_id, kind):
    with sqlite3.connect(client.database_path) as connection:
        if kind == "unknown_fixture_id":
            connection.execute("UPDATE selected_synthetic_sources SET fixture_id='fixture-legitimo-esperado' WHERE id=?", (source["id"],))
        elif kind == "canonical_bytes":
            connection.execute("UPDATE mission_knowledge SET content='conteúdo alterado' WHERE id=?", (source["knowledge_id"],))
        elif kind == "stored_hash":
            connection.execute("UPDATE selected_synthetic_sources SET content_sha256=? WHERE id=?", ("0" * 64, source["id"]))
        elif kind == "catalog_version":
            connection.execute("UPDATE selected_synthetic_sources SET catalog_version='999.0.0' WHERE id=?", (source["id"],))
        elif kind == "snapshot_missing":
            connection.execute("UPDATE mission_artifact_reviews SET artifact_snapshot_json=NULL WHERE id=?", (source["review_id"],))
        elif kind in {"snapshot_adulterated", "snapshot_reference"}:
            raw = connection.execute("SELECT artifact_snapshot_json FROM mission_artifact_reviews WHERE id=?", (source["review_id"],)).fetchone()[0]
            snapshot = json.loads(raw)
            if kind == "snapshot_adulterated":
                snapshot["content"] += " adulterado"
            else:
                snapshot["source_refs"][0]["source_id"] = "synthetic:selected:outro-registro"
            connection.execute("UPDATE mission_artifact_reviews SET artifact_snapshot_json=?, artifact_sha256=? WHERE id=?",
                               (json.dumps(snapshot, ensure_ascii=False), _sha(snapshot), source["review_id"]))
        elif kind == "domain_link":
            connection.execute("UPDATE selected_synthetic_sources SET domain_id='dom_synthetic_b' WHERE id=?", (source["id"],))
        elif kind == "knowledge_review_link":
            connection.execute("UPDATE mission_knowledge SET source_review_id=NULL WHERE id=?", (source["knowledge_id"],))
        elif kind == "owner_link":
            connection.execute("UPDATE selected_synthetic_sources SET owner='owner_b' WHERE id=?", (source["id"],))
        else:
            raise AssertionError(kind)
        fk = connection.execute("PRAGMA foreign_key_check").fetchall()
    return fk


@pytest.mark.parametrize("kind", [
    "unknown_fixture_id", "canonical_bytes", "stored_hash", "catalog_version",
    "snapshot_missing", "snapshot_adulterated", "snapshot_reference",
    "domain_link", "knowledge_review_link",
])
def test_invalid_source_proof_is_quarantined_on_every_read_surface(client, kind):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id, source, initial_review, knowledge = _approved_source(client, csrf)
    fk = _tamper_source(client, source, mission_id, kind)
    assert fk == []

    source_path = f"/real/missions/{mission_id}/sources"
    source_list = client.get(source_path, headers={"origin": ORIGIN}).json()["items"]
    assert len(source_list) == 1
    item = source_list[0]
    assert item["classification"] == "unverified"
    assert item["selection_state"] == "quarantined"
    assert item["content_withheld"] is True
    assert item["fixture_id"] is None
    assert item["provenance"] is None
    assert "tarefas-de-exemplo" not in json.dumps(item, ensure_ascii=False)
    assert "fixture-legitimo-esperado" not in json.dumps(item, ensure_ascii=False)

    mission = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()["mission"]
    artifact = next(entry for entry in mission["artifacts"] if entry["id"] == initial_review["artifact_id"])
    assert artifact["content"] == ""
    assert artifact["content_withheld"] is True
    assert artifact["review_state"] == "draft"

    review = client.get(f"/real/reviews/{source['review_id']}", headers={"origin": ORIGIN}).json()
    assert review["state"] == "pending"
    assert review["decision_state_proven"] is False
    assert review["content_withheld"] is True
    assert review["artifact"]["content"] == ""
    assert review["history"] == []
    assert review["history_withheld"] is True
    assert client.get("/real/reviews?state=approved", headers={"origin": ORIGIN}).json()["items"] == []

    quarantined_knowledge = next(
        entry for entry in client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"]
        if entry["id"] == knowledge["id"]
    )
    assert quarantined_knowledge["state"] == "quarantined"
    assert quarantined_knowledge["content"] == ""
    assert quarantined_knowledge["decision"] is None
    assert quarantined_knowledge["content_sha256"] is None
    assert client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN}).json()["included"] == []

    fixture = fixture_for("tarefas-de-exemplo")
    assert fixture is not None
    decision = {"decision": "approved", "expected_content_sha256": fixture["content_sha256"], "idempotency_key": f"r5-refuse-{kind}"}
    assert client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=decision).status_code == 409
    refused = client.post(f"/real/reviews/{source['review_id']}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_revision": 2,
        "expected_artifact_sha256": initial_review["artifact_sha256"],
        "idempotency_key": f"r5-refuse-review-{kind}",
    })
    assert refused.status_code == 422


def test_owner_and_mission_mismatch_never_reconstruct_source_proof(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id, source, review, _ = _approved_source(client, csrf)
    with sqlite3.connect(client.database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("UPDATE selected_synthetic_sources SET owner='owner_b' WHERE id=?", (source["id"],))
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert prove_source(connection, source["id"], "owner_b", mission_id).trusted is False
        assert prove_source(connection, source["id"], "owner", mission_id).trusted is False
    assert client.get(f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN}).json()["items"] == []
    parent = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()["mission"]
    assert next(artifact for artifact in parent["artifacts"] if artifact["id"] == review["artifact_id"])["content"] == ""
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM selected_synthetic_sources WHERE id=?", (source["id"],)).fetchone()[0] == 1


def test_mission_mismatch_with_valid_foreign_key_is_quarantined_on_both_missions(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id, source, review, _ = _approved_source(client, csrf)
    other = client.post("/real/missions", headers=_headers(csrf), json={
        "title": "Missão de vínculo alternativo", "domain_id": "dom_synthetic_a",
        "idempotency_key": "r5-valid-foreign-mission-link",
    })
    assert other.status_code == 201, other.text
    other_id = other.json()["mission"]["id"]
    with sqlite3.connect(client.database_path) as connection:
        connection.execute("UPDATE selected_synthetic_sources SET mission_id=? WHERE id=?", (other_id, source["id"]))
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    other_sources = client.get(f"/real/missions/{other_id}/sources", headers={"origin": ORIGIN}).json()["items"]
    assert len(other_sources) == 1
    assert other_sources[0]["selection_state"] == "quarantined"
    assert other_sources[0]["fixture_id"] is None
    original_mission = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()["mission"]
    original_artifact = next(item for item in original_mission["artifacts"] if item["id"] == review["artifact_id"])
    assert original_artifact["content"] == ""
    assert original_artifact["review_state"] == "draft"


def test_read_and_reconcile_are_serialized_without_deadlock_and_restore_stays_quarantined(client, tmp_path):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id, source, _, _ = _approved_source(client, csrf)
    store = client.app.state.memory_store
    with ThreadPoolExecutor(max_workers=2) as pool:
        read = pool.submit(client.get, f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN})
        reconcile = pool.submit(reconcile_legacy_selected_sources, store)
        response = read.result(timeout=5)
        reconcile.result(timeout=5)
    assert response.status_code == 200
    assert response.json()["items"][0]["classification"] == "synthetic_verified"

    with sqlite3.connect(client.database_path) as connection:
        connection.execute("UPDATE selected_synthetic_sources SET fixture_id='fixture-inexistente' WHERE id=?", (source["id"],))
    archive = create_backup(client.database_path, tmp_path / "backups", "senha-sintetica-r5-backup")
    restored = restore_backup(archive, tmp_path / "restore", "senha-sintetica-r5-backup")
    restored_store = SQLiteMemoryStore(restored)
    restored_store.initialize()
    reconcile_legacy_selected_sources(restored_store)
    with restored_store.transaction() as connection:
        row = connection.execute("SELECT * FROM selected_synthetic_sources WHERE id=?", (source["id"],)).fetchone()
        assert row is not None
        assert row["classification"] == "unverified"
        assert row["state"] == "quarantined"
        assert prove_source(connection, source["id"], row["owner"], mission_id).trusted is False
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("first_order", ["read_then_reconcile", "reconcile_then_read"])
def test_read_and_reconcile_lock_orders_complete_without_deadlock(client, monkeypatch, first_order):
    import selected_source_api as selected_source_module
    import source_admission as source_admission_module

    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id, source, _, _ = _approved_source(client, csrf)
    entered_proof = threading.Event()
    release_proof = threading.Event()

    def pause_first_proof(original):
        def wrapped(*args, **kwargs):
            if not entered_proof.is_set():
                entered_proof.set()
                if not release_proof.wait(timeout=5):
                    raise TimeoutError("probe R5 não liberou a primeira prova")
            return original(*args, **kwargs)
        return wrapped

    if first_order == "read_then_reconcile":
        monkeypatch.setattr(
            selected_source_module, "resolve_trusted_source_projection",
            pause_first_proof(selected_source_module.resolve_trusted_source_projection),
        )
    else:
        monkeypatch.setattr(source_admission_module, "prove_source",
                            pause_first_proof(source_admission_module.prove_source))

    store = client.app.state.memory_store
    read_future = reconcile_future = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            if first_order == "read_then_reconcile":
                read_future = pool.submit(client.get, f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN})
                assert entered_proof.wait(timeout=5), "leitura não entrou na transação de prova"
                reconcile_future = pool.submit(reconcile_legacy_selected_sources, store)
            else:
                reconcile_future = pool.submit(reconcile_legacy_selected_sources, store)
                assert entered_proof.wait(timeout=5), "reconciliação não entrou na transação de prova"
                read_future = pool.submit(client.get, f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN})
        finally:
            release_proof.set()
        response = read_future.result(timeout=5)
        reconciled = reconcile_future.result(timeout=5)
    assert response.status_code == 200
    assert response.json()["items"][0]["classification"] == "synthetic_verified"
    assert reconciled == 0
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT state FROM selected_synthetic_sources WHERE id=?", (source["id"],)).fetchone()[0] == "selected"


def test_restart_reconciles_invalid_persisted_source_before_authorized_reads(client, monkeypatch):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id, source, _, _ = _approved_source(client, csrf)
    with sqlite3.connect(client.database_path) as connection:
        connection.execute("UPDATE selected_synthetic_sources SET fixture_id='unknown-after-backup' WHERE id=?", (source["id"],))
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", "senha-sintetica-de-missao")
    restarted = create_app(LocalServerConfig(), database_path=client.database_path)
    with TestClient(restarted, base_url="http://127.0.0.1", client=("127.0.0.1", 50992)) as after_restart:
        restarted_csrf = login(after_restart)
        mission_all_grants(after_restart, restarted_csrf)
        reread = after_restart.get(f"/real/missions/{mission_id}/sources", headers={"origin": ORIGIN}).json()["items"]
        assert len(reread) == 1
        assert reread[0]["classification"] == "unverified"
        assert reread[0]["selection_state"] == "quarantined"
        with sqlite3.connect(client.database_path) as connection:
            row = connection.execute("SELECT classification, state FROM selected_synthetic_sources WHERE id=?", (source["id"],)).fetchone()
        assert row == ("unverified", "quarantined")


def _clone_import(document, name):
    result = copy.deepcopy(document)
    result["id"] = f"mission_r5_import_{name}"
    for index, event in enumerate(result["events"]):
        event["id"] = f"event_r5_import_{name}_{index}"
    return result


@pytest.mark.parametrize("claim", ["approved", "rejected", "changes_requested", "approved_locally", "not_required"])
def test_imported_decision_claims_are_quarantined_without_ledger_or_context(client, claim):
    csrf = login(client)
    mission_all_grants(client, csrf)
    source_record, _ = create_and_run_step(client, csrf, "Missão de origem para importação")
    source = source_record["mission"]
    imported = _clone_import(source, claim.replace("_", "a"))
    for artifact in imported["artifacts"]:
        artifact["review_state"] = claim
        artifact["reviewed_at"] = "2026-09-27T00:00:00+00:00"
    response = client.post("/real/missions/import", headers=_headers(csrf), json={
        "missions": [imported], "idempotency_key": f"r5-import-claim-{claim}", "confirm": True,
    })
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == []
    assert response.json()["quarantined"][0]["index"] == 0
    assert "decisão de revisão sem ledger local" in response.json()["quarantined"][0]["reason"]
    assert client.get(f"/real/missions/{imported['id']}", headers={"origin": ORIGIN}).status_code == 404
    assert client.get(f"/real/knowledge/context/{imported['id']}", headers={"origin": ORIGIN}).status_code == 404
    assert client.post(f"/real/missions/{imported['id']}/transition", headers=_headers(csrf), json={
        "action": "run_next", "expected_revision": 1, "idempotency_key": f"r5-no-conclude-{claim}",
    }).status_code == 404
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM missions WHERE id=?", (imported["id"],)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM mission_review_decisions WHERE mission_id=?", (imported["id"],)).fetchone()[0] == 0


def test_pending_import_is_normalized_to_local_draft_and_replay_is_idempotent(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Documento pendente para importar")
    mission_id = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()["mission_id"]
    document = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()["mission"]
    imported = _clone_import(document, "pending")
    for artifact in imported["artifacts"]:
        artifact["review_state"] = "pending"
    body = {"missions": [imported], "idempotency_key": "r5-pending-import-replay", "confirm": True}
    first = client.post("/real/missions/import", headers=_headers(csrf), json=body)
    replay = client.post("/real/missions/import", headers=_headers(csrf), json=body)
    assert first.status_code == replay.status_code == 200
    assert first.json()["accepted"] == [imported["id"]]
    assert replay.json()["replayed"] is True
    reread = client.get(f"/real/missions/{imported['id']}", headers={"origin": ORIGIN}).json()["mission"]
    assert all(artifact["review_state"] == "draft" and artifact["reviewed_at"] is None
               for artifact in reread["artifacts"])
    review_list = client.get(f"/real/missions/{imported['id']}/reviews", headers={"origin": ORIGIN}).json()["items"]
    assert review_list and all(item["state"] == "pending" for item in review_list)
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mission_review_decisions WHERE mission_id=?", (imported["id"],)).fetchone()[0] == 0


def test_local_ledger_approval_survives_contradictory_import_claim(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Decisão local para preservar")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    approval = client.post(f"/real/reviews/{review_id}/decide", headers=_headers(csrf), json={
        "decision": "approved", "expected_revision": 1,
        "expected_artifact_sha256": detail["artifact_sha256"], "idempotency_key": "r5-local-ledger-approval",
    })
    assert approval.status_code == 200
    mission = client.get(f"/real/missions/{detail['mission_id']}", headers={"origin": ORIGIN}).json()["mission"]
    contradictory = copy.deepcopy(mission)
    contradictory["artifacts"][0]["review_state"] = "rejected"
    response = client.post("/real/missions/import", headers=_headers(csrf), json={
        "missions": [contradictory], "idempotency_key": "r5-contradictory-import", "confirm": True,
    })
    assert response.status_code == 200
    assert response.json()["accepted"] == []
    preserved = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert preserved["state"] == "approved"
    assert preserved["history"][0]["decision"] == "approved"
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mission_review_decisions WHERE review_id=?", (review_id,)).fetchone()[0] == 1


def test_concurrent_identical_pending_imports_create_one_record_and_no_decisions(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    source = client.post("/real/missions", headers=_headers(csrf), json={
        "title": "Missão importada concorrente", "domain_id": "dom_synthetic_a",
        "idempotency_key": "r5-import-concurrent-source",
    }).json()["mission"]
    imported = _clone_import(source, "concurrent")
    body = {"missions": [imported], "idempotency_key": "r5-import-concurrent-same-key", "confirm": True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, "/real/missions/import", headers=_headers(csrf), json=body) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert [result.status_code for result in results] == [200, 200]
    assert sorted(result.json()["replayed"] for result in results) == [False, True]
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM missions WHERE id=?", (imported["id"],)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM mission_review_decisions WHERE mission_id=?", (imported["id"],)).fetchone()[0] == 0


def test_other_principal_cannot_import_review_authority(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    source_record, _ = create_and_run_step(client, csrf, "Fonte para outro principal")
    source = source_record["mission"]
    imported = _clone_import(source, "other_principal")
    imported["artifacts"][0]["review_state"] = "approved"
    token = "r5-other-principal-session"
    put_session_for_tests(token, "owner_b", "r5-other-principal-csrf")
    put_grant_for_tests(Grant(
        id="r5-other-principal-write", principal="owner_b", connector="mission_sim",
        resource_ids=frozenset({"mission:write"}), domain_ids=frozenset({"dom_synthetic_a"}),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    other = TestClient(client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50991))
    other.cookies.set("jarvis_session", token)
    response = other.post("/real/missions/import", headers=_headers("r5-other-principal-csrf"), json={
        "missions": [imported], "idempotency_key": "r5-other-principal-import", "confirm": True,
    })
    assert response.status_code == 200
    assert response.json()["accepted"] == []
    assert response.json()["quarantined"]
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM missions WHERE owner='owner_b'").fetchone()[0] == 0
