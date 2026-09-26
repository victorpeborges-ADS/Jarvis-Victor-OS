"""Synthetic knowledge requires a separate human decision before context inclusion."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from backup_recovery import create_backup, restore_backup
from local_security import Grant, put_grant_for_tests, put_session_for_tests
from test_review_api import (
    ORIGIN, client, create_and_run_step, login, mission_all_grants,
)


def _headers(csrf):
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def _decide_artifact(client, csrf, review_id, detail):
    return client.post(
        f"/real/reviews/{review_id}/decide", headers=_headers(csrf),
        json={"decision": "approved", "expected_revision": 1,
              "expected_artifact_sha256": detail["artifact_sha256"],
              "idempotency_key": f"approve-source-{review_id}"},
    )


def test_staged_knowledge_needs_approved_source_and_separate_decision(client, tmp_path):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Ideia de teste com origem")
    review = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    mission_id = review["mission_id"]
    listed = client.get("/real/knowledge", headers={"origin": ORIGIN})
    assert listed.status_code == 200
    knowledge = listed.json()["items"][0]
    assert knowledge["state"] == "staged"
    before = client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN})
    assert before.status_code == 200
    assert before.json()["included"] == []
    assert before.json()["omitted"][0]["reason"] == "aguardando_revisao"

    body = {"decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
            "idempotency_key": "knowledge-approval-key"}
    premature = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=body)
    assert premature.status_code == 409
    assert _decide_artifact(client, csrf, review_id, review).status_code == 200
    still_staged = client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN})
    assert still_staged.json()["included"] == []
    approved = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=body)
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "approved"
    assert approved.json()["source_review_id"] == review_id
    replay = client.post(f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf), json=body)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    bundle = client.get(f"/real/knowledge/context/{mission_id}", headers={"origin": ORIGIN})
    assert bundle.status_code == 200
    assert [item["knowledge_id"] for item in bundle.json()["included"]] == [knowledge["id"]]
    assert bundle.json()["included"][0]["source_artifact_sha256"] == review["artifact_sha256"]
    limited = client.get(f"/real/knowledge/context/{mission_id}?max_chars=1", headers={"origin": ORIGIN})
    assert limited.json()["included"] == []
    assert limited.json()["omitted"][0]["reason"] == "limite_de_tamanho"
    current = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
    context_step = client.post(
        f"/real/missions/{mission_id}/transition", headers=_headers(csrf),
        json={"action": "run_next", "expected_revision": current["revision"],
              "idempotency_key": "run-approved-context"},
    )
    assert context_step.status_code == 200, context_step.text
    context_artifact = next(item for item in context_step.json()["mission"]["artifacts"]
                            if item["kind"] == "context_bundle")
    assert knowledge["content"] in context_artifact["content"]
    assert review_id in context_artifact["content"]
    assert context_artifact["source_refs"][0]["source_id"] == f"synthetic:knowledge:{knowledge['id']}"
    assert context_artifact["skill_id"] == "build-context"
    archive = create_backup(client.database_path, tmp_path / "backups", "senha-sintetica-backup-conhecimento")
    restored = restore_backup(archive, tmp_path / "restore", "senha-sintetica-backup-conhecimento")
    with sqlite3.connect(restored) as con:
        assert con.execute("SELECT COUNT(*) FROM mission_knowledge_decisions").fetchone()[0] == 1
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_knowledge_isolated_by_principal_and_grant(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Conhecimento isolado")
    review = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    knowledge = client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"][0]
    other_token = "other-knowledge-session"
    put_session_for_tests(other_token, "owner_b", "other-knowledge-csrf")
    put_grant_for_tests(Grant(
        id="other-knowledge-read", principal="owner_b", connector="mission_sim",
        resource_ids=frozenset({"mission:read", "mission:review"}),
        domain_ids=frozenset({"dom_synthetic_a"}),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    from fastapi.testclient import TestClient
    with TestClient(client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50995)) as other:
        other.cookies.set("jarvis_session", other_token)
        assert other.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"] == []
        assert other.get(f"/real/knowledge/context/{review['mission_id']}",
                         headers={"origin": ORIGIN}).status_code == 404
        denied = other.post(
            f"/real/knowledge/{knowledge['id']}/decide",
            headers=_headers("other-knowledge-csrf"),
            json={"decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
                  "idempotency_key": "cross-owner-knowledge"},
        )
        assert denied.status_code == 404


def test_knowledge_grant_revoke_before_commit(client, monkeypatch):
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Revogação de conhecimento")
    review = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert _decide_artifact(client, csrf, review_id, review).status_code == 200
    knowledge = client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"][0]
    import knowledge_api
    original = knowledge_api.mission_review_confirmed
    entered, release = threading.Event(), threading.Event()

    @contextmanager
    def paused_guard(*args):
        entered.set()
        assert release.wait(5)
        with original(*args):
            yield

    monkeypatch.setattr(knowledge_api, "mission_review_confirmed", paused_guard)
    sink = []
    def decide():
        sink.append(client.post(
            f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf),
            json={"decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
                  "idempotency_key": "knowledge-revoke-race"},
        ).status_code)
    worker = threading.Thread(target=decide)
    worker.start()
    assert entered.wait(5)
    try:
        assert client.post(f"/real/grants/{grants['review']}/revoke",
                           headers=_headers(csrf)).status_code == 200
    finally:
        release.set()
        worker.join(timeout=5)
    assert sink == [403]
    with sqlite3.connect(client.database_path) as con:
        assert con.execute("SELECT COUNT(*) FROM mission_knowledge_decisions").fetchone()[0] == 0


def test_context_omits_changed_content_and_source(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Integridade do contexto")
    review = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert _decide_artifact(client, csrf, review_id, review).status_code == 200
    knowledge = client.get("/real/knowledge", headers={"origin": ORIGIN}).json()["items"][0]
    assert client.post(
        f"/real/knowledge/{knowledge['id']}/decide", headers=_headers(csrf),
        json={"decision": "approved", "expected_content_sha256": knowledge["content_sha256"],
              "idempotency_key": "knowledge-integrity-approve"},
    ).status_code == 200
    path = f"/real/knowledge/context/{review['mission_id']}"
    assert len(client.get(path, headers={"origin": ORIGIN}).json()["included"]) == 1
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE mission_knowledge SET content='adulterado' WHERE id=?", (knowledge["id"],))
    changed = client.get(path, headers={"origin": ORIGIN}).json()
    assert changed["included"] == []
    assert changed["omitted"][0]["reason"] == "integridade"
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE mission_knowledge SET content=? WHERE id=?", (knowledge["content"], knowledge["id"]))
        con.execute("UPDATE mission_artifact_reviews SET state='pending' WHERE id=?", (review_id,))
    stale = client.get(path, headers={"origin": ORIGIN}).json()
    assert stale["included"] == []
    assert stale["omitted"][0]["reason"] == "fonte_desatualizada"
