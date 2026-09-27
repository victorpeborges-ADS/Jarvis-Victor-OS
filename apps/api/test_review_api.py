"""Adversarial and functional backend tests for G5 artifact review and human approval."""

from __future__ import annotations

import json
import hashlib
import os
import signal
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backup_recovery import create_backup, restore_backup
from local_security import Grant, put_grant_for_tests, put_session_for_tests, reset_state
from main import create_app
from server_config import LocalServerConfig

PASSPHRASE = "senha-sintetica-de-missao"
ORIGIN = "http://127.0.0.1:3000"
ROOT = Path(__file__).resolve().parent


def _expire(seconds: float = 86400) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    app = create_app(LocalServerConfig(), database_path=private / "memory.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50993)) as test_client:
        test_client.database_path = app.state.memory_store.path
        yield test_client
    reset_state()


def login(client: TestClient) -> str:
    response = client.post("/real/session", json={"passphrase": PASSPHRASE}, headers={"origin": ORIGIN})
    assert response.status_code == 201, response.text
    return response.json()["csrf_token"]


def grant(client: TestClient, csrf: str, resource: str, domain: str = "dom_synthetic_a", connector: str = "mission_sim", expires_at: str | None = None) -> str:
    response = client.post(
        "/real/grants",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "connector": connector,
            "permission": "read",
            "resource_ids": [resource],
            "domain_ids": [domain],
            "expires_at": expires_at or _expire(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def mission_all_grants(client: TestClient, csrf: str, domain: str = "dom_synthetic_a") -> dict[str, str]:
    ids = {}
    ids["read"] = grant(client, csrf, "mission:read", domain)
    ids["write"] = grant(client, csrf, "mission:write", domain)
    ids["review"] = grant(client, csrf, "mission:review", domain)
    return ids


def create_and_run_step(client: TestClient, csrf: str, title: str = "Missão com rascunho", domain: str = "dom_synthetic_a") -> tuple[dict, str]:
    create_resp = client.post(
        "/real/missions",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"title": title, "domain_id": domain, "idempotency_key": f"create-{title[:20]}-{time.time()}"},
    )
    assert create_resp.status_code == 201, create_resp.text
    mission_id = create_resp.json()["mission"]["id"]

    step_resp = client.post(
        f"/real/missions/{mission_id}/transition",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"action": "run_next", "expected_revision": 1, "idempotency_key": f"step-{mission_id}-1"},
    )
    assert step_resp.status_code == 200, step_resp.text
    reviews = client.get("/real/reviews", headers={"origin": ORIGIN}).json()["items"]
    rev = next(r for r in reviews if r["mission_id"] == mission_id)
    return step_resp.json(), rev["id"]


def test_draft_appears_in_review_queue_and_review_grant_is_required(client):
    csrf = login(client)
    grant(client, csrf, "mission:read")
    grant(client, csrf, "mission:write")

    _, review_id = create_and_run_step(client, csrf, "Draft na fila")

    # Queue list works with mission:read
    queue = client.get("/real/reviews", headers={"origin": ORIGIN})
    assert queue.status_code == 200, queue.text
    items = queue.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == review_id
    assert items[0]["state"] == "pending"

    # Detail query works with mission:read
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN})
    assert detail.status_code == 200, detail.text
    assert detail.json()["state"] == "pending"
    assert "artifact" in detail.json()
    assert detail.json()["artifact"]["review_state"] == "draft"

    # Decide without mission:review grant -> 403
    decide_body = {
        "decision": "approved",
        "expected_revision": 1,
        "expected_artifact_sha256": detail.json()["artifact_sha256"],
        "idempotency_key": "decide-key-fail-403",
    }
    denied = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=decide_body,
    )
    assert denied.status_code == 403
    assert "concessão de revisão ausente" in denied.json()["detail"]

    # Now grant mission:review
    grant(client, csrf, "mission:review")
    approved = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=decide_body,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "approved"
    assert approved.json()["decision_actor"] == "owner"
    assert approved.json()["decided_at"] is not None


def test_approved_decision_appends_ledger_event_and_persists_after_restart(client, tmp_path, monkeypatch):
    csrf = login(client)
    mission_all_grants(client, csrf)

    _, review_id = create_and_run_step(client, csrf, "Aprovação persistente")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()

    approved = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "approved",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "idempotency_key": "decide-persist-ok-01",
        },
    )
    assert approved.status_code == 200
    res = approved.json()
    assert res["state"] == "approved"
    assert res["revision"] == 2

    # Check detail has history
    reread = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert len(reread["history"]) == 1
    assert reread["history"][0]["decision"] == "approved"

    # Check parent mission document updated review_state
    parent_mission = client.get(f"/real/missions/{detail['mission_id']}", headers={"origin": ORIGIN}).json()["mission"]
    art = next(a for a in parent_mission["artifacts"] if a["id"] == detail["artifact_id"])
    assert art["review_state"] == "approved"
    assert art["reviewed_at"] is not None
    assert any(e["type"] == "artifact_reviewed" for e in parent_mission["events"])

    # Restart API against same SQLite store
    database = client.database_path
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    restarted = create_app(LocalServerConfig(), database_path=database)
    with TestClient(restarted, base_url="http://127.0.0.1", client=("127.0.0.1", 50994)) as again:
        again_csrf = login(again)
        mission_all_grants(again, again_csrf)

        restored_review = again.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
        assert restored_review["state"] == "approved"
        assert len(restored_review["history"]) == 1
        assert restored_review["history"][0]["decision"] == "approved"

        restored_mission = again.get(f"/real/missions/{detail['mission_id']}", headers={"origin": ORIGIN}).json()["mission"]
        restored_art = next(a for a in restored_mission["artifacts"] if a["id"] == detail["artifact_id"])
        assert restored_art["review_state"] == "approved"


def test_backup_and_restore_preserves_reviews_and_decisions(client, tmp_path, monkeypatch):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Backup com revisões")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()

    client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "approved",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "idempotency_key": "decide-backup-01",
        },
    )

    backup_dir = tmp_path / "backups"
    restore_dir = tmp_path / "restores"
    archive = create_backup(client.database_path, backup_dir, "senha-super-secreta-backup-1234")
    restored_db = restore_backup(archive, restore_dir, "senha-super-secreta-backup-1234")

    with sqlite3.connect(restored_db) as con:
        con.row_factory = sqlite3.Row
        rev = con.execute("SELECT * FROM mission_artifact_reviews WHERE id=?", (review_id,)).fetchone()
        assert rev is not None
        assert rev["state"] == "approved"
        decs = con.execute("SELECT * FROM mission_review_decisions WHERE review_id=?", (review_id,)).fetchall()
        assert len(decs) == 1
        assert decs[0]["decision"] == "approved"


def test_idempotency_replay_same_body_and_conflict_different_body(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Idempotência de revisão")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()

    body = {
        "decision": "approved",
        "expected_revision": 1,
        "expected_artifact_sha256": detail["artifact_sha256"],
        "idempotency_key": "idem-review-key-01",
    }
    first = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=body,
    )
    assert first.status_code == 200
    assert first.json()["replayed"] is False

    # Exact same request replays
    replay = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=body,
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["id"] == review_id

    # Same idempotency key with different decision / reason -> 409
    clash = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "rejected",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "idempotency_key": "idem-review-key-01",
            "reason": "motivo diferente",
        },
    )
    assert clash.status_code == 409
    assert "idempotência reutilizada com corpo diferente" in clash.json()["detail"]


def test_concurrent_conflicting_decisions_on_same_version_have_one_winner(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Corrida de decisão")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()

    results = []

    def make_decision(decision: str, reason: str | None, key: str):
        with TestClient(client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50993)) as c:
            c.cookies.set("jarvis_session", client.cookies.get("jarvis_session"))
            resp = c.post(
                f"/real/reviews/{review_id}/decide",
                headers={"origin": ORIGIN, "x-csrf-token": csrf},
                json={
                    "decision": decision,
                    "expected_revision": 1,
                    "expected_artifact_sha256": detail["artifact_sha256"],
                    "reason": reason,
                    "idempotency_key": key,
                },
            )
            results.append((decision, resp.status_code, resp.json()))

    t1 = threading.Thread(target=make_decision, args=("approved", None, "race-key-01"))
    t2 = threading.Thread(target=make_decision, args=("rejected", "rejeitado por corrida", "race-key-02"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    statuses = [r[1] for r in results]
    assert sorted(statuses) == [200, 409]
    winner = next(r for r in results if r[1] == 200)
    loser = next(r for r in results if r[1] == 409)
    assert loser[2]["detail"] in ("revisão divergente", "revisão já encerrada")

    final = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert final["state"] == winner[0]
    assert len(final["history"]) == 1


def test_cross_principal_and_unauthorized_isolation(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Isolamento principal")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()

    # Other principal with mission:review cannot see or decide
    other = TestClient(client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50996))
    other.cookies.set("jarvis_session", "owner-b-session-token")
    put_session_for_tests("owner-b-session-token", "owner_b", "csrf-owner-b-token")
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    put_grant_for_tests(Grant(
        id="grant-owner-b-review", principal="owner_b", connector="mission_sim",
        resource_ids=frozenset({"mission:read", "mission:review"}), domain_ids=frozenset({"dom_synthetic_a"}), expires_at=expires,
    ))

    # Other principal sees 404
    hidden_get = other.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN})
    assert hidden_get.status_code == 404

    hidden_decide = other.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": "csrf-owner-b-token"},
        json={
            "decision": "approved",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "idempotency_key": "other-decide-01",
        },
    )
    assert hidden_decide.status_code == 404

    # Other principal queue is empty
    assert other.get("/real/reviews", headers={"origin": ORIGIN}).json()["items"] == []

    # Original untouched
    untouched = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert untouched["state"] == "pending"


def test_changes_requested_and_revised_version_requires_new_review(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Solicitação de ajustes")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()

    # Rejection or changes_requested without reason -> 422
    no_reason = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "changes_requested",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "idempotency_key": "req-no-reason",
        },
    )
    assert no_reason.status_code == 422

    # Request changes with reason -> 200
    changed = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "changes_requested",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "reason": "Favor corrigir formatação e incluir sumário.",
            "idempotency_key": "req-ok-01",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["state"] == "changes_requested"

    # Revise review produces version 2 with state pending
    revised = client.post(
        f"/real/reviews/{review_id}/revise",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "new_content": "Conteúdo corrigido com sumário executivo.",
            "idempotency_key": "revise-content-01",
        },
    )
    assert revised.status_code == 200
    v2 = revised.json()
    assert v2["artifact_version"] == 2
    assert v2["state"] == "pending"
    assert v2["artifact"]["content"] == "Conteúdo corrigido com sumário executivo."

    stale_decision = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "approved",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "idempotency_key": "stale-review-v1-decision",
        },
    )
    assert stale_decision.status_code == 409, stale_decision.text

    # Version 1 remains changes_requested and terminal
    v1 = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert v1["state"] == "changes_requested"
    assert v1["artifact"]["content"] == detail["artifact"]["content"]
    assert v1["artifact"]["content"] != v2["artifact"]["content"]

    # Version 2 can be approved independently
    v2_approved = client.post(
        f"/real/reviews/{v2['id']}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "approved",
            "expected_revision": 1,
            "expected_artifact_sha256": v2["artifact_sha256"],
            "idempotency_key": "v2-approved-key",
        },
    )
    assert v2_approved.status_code == 200
    assert v2_approved.json()["state"] == "approved"


def test_mission_review_operations_can_reuse_create_key_and_replay_history(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    shared_key = "create-review-shared-key-r2"
    created = client.post(
        "/real/missions",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"title": "chave compartilhada entre operações", "domain_id": "dom_synthetic_a",
              "idempotency_key": shared_key},
    )
    assert created.status_code == 201, created.text
    mission_id = created.json()["mission"]["id"]
    step = client.post(
        f"/real/missions/{mission_id}/transition",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"action": "run_next", "expected_revision": 1, "idempotency_key": "review-scope-step-r2"},
    )
    assert step.status_code == 200, step.text
    review = next(
        item for item in client.get("/real/reviews", headers={"origin": ORIGIN}).json()["items"]
        if item["mission_id"] == mission_id
    )
    detail = client.get(f"/real/reviews/{review['id']}", headers={"origin": ORIGIN}).json()
    decision_body = {
        "decision": "changes_requested",
        "expected_revision": 1,
        "expected_artifact_sha256": detail["artifact_sha256"],
        "reason": "Revisar o sumário para esta demonstração sintética.",
        "idempotency_key": shared_key,
    }

    decision = client.post(
        f"/real/reviews/{review['id']}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=decision_body,
    )
    replayed_decision = client.post(
        f"/real/reviews/{review['id']}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=decision_body,
    )
    assert decision.status_code == 200, decision.text
    assert replayed_decision.status_code == 200
    assert replayed_decision.json()["replayed"] is True

    revision_body = {"new_content": "Conteúdo revisado com sumário.", "idempotency_key": shared_key}
    revision = client.post(
        f"/real/reviews/{review['id']}/revise",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=revision_body,
    )
    replayed_revision = client.post(
        f"/real/reviews/{review['id']}/revise",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json=revision_body,
    )
    assert revision.status_code == 200, revision.text
    assert replayed_revision.status_code == 200
    assert replayed_revision.json()["replayed"] is True

    with sqlite3.connect(client.database_path) as connection:
        operations = connection.execute(
            "SELECT operation FROM mission_idempotency WHERE owner='owner' AND idempotency_key=? "
            "ORDER BY operation",
            (shared_key,),
        ).fetchall()
        review_history = connection.execute(
            "SELECT COUNT(*) FROM mission_review_decisions WHERE owner='owner' AND idempotency_key=?",
            (shared_key,),
        ).fetchone()[0]
    assert [row[0] for row in operations] == [
        "mission.create", "mission.review.decide", "mission.review.revise",
    ]
    assert review_history == 1


def test_ledger_snapshot_hash_and_immutability(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Snapshot verificável")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    response = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"decision": "approved", "expected_revision": 1,
              "expected_artifact_sha256": detail["artifact_sha256"],
              "idempotency_key": "snapshot-hash-key"},
    )
    assert response.status_code == 200
    with sqlite3.connect(client.database_path) as con:
        row = con.execute(
            "SELECT id, artifact_sha256, snapshot_json FROM mission_review_decisions WHERE review_id=?",
            (review_id,),
        ).fetchone()
        snapshot = json.loads(row[2])
        canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        assert hashlib.sha256(canonical.encode()).hexdigest() == row[1]
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE mission_review_decisions SET decision='rejected' WHERE id=?", (row[0],))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("DELETE FROM mission_review_decisions WHERE id=?", (row[0],))


def test_session_closed_before_decision_commit_fails_closed(client, monkeypatch):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Sessão encerrada")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    entered, release = threading.Event(), threading.Event()
    import mission_repository
    def pause():
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(mission_repository, "_pause_review_if_requested", pause)
    sink = []
    def decide():
        sink.append(client.post(
            f"/real/reviews/{review_id}/decide",
            headers={"origin": ORIGIN, "x-csrf-token": csrf},
            json={"decision": "approved", "expected_revision": 1,
                  "expected_artifact_sha256": detail["artifact_sha256"],
                  "idempotency_key": "session-close-race-key"},
        ).status_code)
    worker = threading.Thread(target=decide)
    worker.start()
    assert entered.wait(5)
    try:
        assert client.delete("/real/session", headers={"origin": ORIGIN, "x-csrf-token": csrf}).status_code == 204
    finally:
        release.set()
        worker.join(timeout=5)
    assert sink == [403]
    with sqlite3.connect(client.database_path) as con:
        assert con.execute("SELECT state FROM mission_artifact_reviews WHERE id=?", (review_id,)).fetchone()[0] == "pending"
        assert con.execute("SELECT COUNT(*) FROM mission_review_decisions WHERE review_id=?", (review_id,)).fetchone()[0] == 0


def test_write_grant_revoked_before_revision_commit_fails_closed(client, monkeypatch):
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Escrita revogada")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    assert client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"decision": "changes_requested", "expected_revision": 1,
              "expected_artifact_sha256": detail["artifact_sha256"],
              "reason": "Ajustar", "idempotency_key": "request-before-revoke"},
    ).status_code == 200
    entered, release = threading.Event(), threading.Event()
    import mission_repository
    def pause():
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(mission_repository, "_pause_review_if_requested", pause)
    sink = []
    def revise():
        sink.append(client.post(
            f"/real/reviews/{review_id}/revise",
            headers={"origin": ORIGIN, "x-csrf-token": csrf},
            json={"new_content": "Nova versão", "idempotency_key": "revise-revoke-race"},
        ).status_code)
    worker = threading.Thread(target=revise)
    worker.start()
    assert entered.wait(5)
    try:
        assert client.post(f"/real/grants/{grants['write']}/revoke",
                           headers={"origin": ORIGIN, "x-csrf-token": csrf}).status_code == 200
    finally:
        release.set()
        worker.join(timeout=5)
    assert sink == [403]
    with sqlite3.connect(client.database_path) as con:
        assert con.execute("SELECT COUNT(*) FROM mission_artifact_reviews WHERE artifact_id=?",
                           (detail["artifact_id"],)).fetchone()[0] == 1


def test_review_queue_filters_domain_before_pagination(client):
    csrf = login(client)
    mission_all_grants(client, csrf, "dom_synthetic_a")
    hidden_grants = mission_all_grants(client, csrf, "dom_synthetic_b")
    _, visible_id = create_and_run_step(client, csrf, "Visível", "dom_synthetic_a")
    _, hidden_id = create_and_run_step(client, csrf, "Oculto", "dom_synthetic_b")
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE mission_artifact_reviews SET id='rev_000_hidden' WHERE id=?", (hidden_id,))
        con.execute("UPDATE mission_artifact_reviews SET id='rev_999_visible' WHERE id=?", (visible_id,))
    for resource in ("read", "review"):
        assert client.post(f"/real/grants/{hidden_grants[resource]}/revoke",
                           headers={"origin": ORIGIN, "x-csrf-token": csrf}).status_code == 200
    page = client.get("/real/reviews?limit=1", headers={"origin": ORIGIN})
    assert page.status_code == 200
    assert [item["id"] for item in page.json()["items"]] == ["rev_999_visible"]
    assert page.json()["next_cursor"] is None


def test_corrupt_review_pointer_returns_409_on_mutation(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Ponteiro inválido")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE mission_artifact_reviews SET artifact_snapshot_json='{}' WHERE id=?", (review_id,))
    response = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"decision": "approved", "expected_revision": 1,
              "expected_artifact_sha256": detail["artifact_sha256"],
              "idempotency_key": "corrupt-pointer-decision"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "integridade do registro de revisão"


def test_corrupted_review_data_fails_closed_without_deleting_row(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    _, review_id = create_and_run_step(client, csrf, "Registro corrompido")

    # Corrupt the parent mission document_json
    with sqlite3.connect(client.database_path) as con:
        con.execute("UPDATE missions SET document_json='{invalid json'")

    # Single read of review returns 409
    corrupt_get = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN})
    assert corrupt_get.status_code == 409
    assert corrupt_get.json()["detail"] == "integridade do registro de revisão"

    # List reviews isolates into corrupt list without leaking title or body
    queue = client.get("/real/reviews", headers={"origin": ORIGIN}).json()
    assert any(c["id"] == review_id and c["integrity"] == "corrupt" for c in queue.get("corrupt", []))

    # Row was NOT deleted
    with sqlite3.connect(client.database_path) as con:
        assert con.execute("SELECT COUNT(*) FROM mission_artifact_reviews WHERE id=?", (review_id,)).fetchone()[0] == 1


def test_cancelled_mission_rejects_review_decision(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    step, review_id = create_and_run_step(client, csrf, "Cancelar e revisar")
    detail = client.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()

    # Cancel the mission
    cancelled = client.post(
        f"/real/missions/{detail['mission_id']}/transition",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"action": "cancel", "expected_revision": step["revision"], "idempotency_key": "cancel-before-review"},
    )
    assert cancelled.status_code == 200

    # Deciding review on cancelled mission fails
    attempt = client.post(
        f"/real/reviews/{review_id}/decide",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "decision": "approved",
            "expected_revision": 1,
            "expected_artifact_sha256": detail["artifact_sha256"],
            "idempotency_key": "decide-cancelled-mission",
        },
    )
    assert attempt.status_code == 422
    assert "missão cancelada" in attempt.json()["detail"]


def test_revoked_or_expired_review_grant_during_pause_fails_closed(tmp_path):
    port = 18872
    pause = tmp_path / "pause_review.txt"
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    database = private / "memory.sqlite3"
    env = os.environ.copy()
    env.update({
        "JARVIS_BIND_HOST": "127.0.0.1",
        "JARVIS_BIND_PORT": str(port),
        "JARVIS_DATABASE_PATH": str(database),
        "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE,
        "JARVIS_TEST_PAUSE_REVIEW_FILE": str(pause),
    })
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "python"), "serve.py"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.4).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)

    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=8) as http:
            login_resp = http.post("/real/session", json={"passphrase": PASSPHRASE}, headers={"origin": ORIGIN})
            csrf = login_resp.json()["csrf_token"]
            headers = {"origin": ORIGIN, "x-csrf-token": csrf}

            http.post("/real/grants", headers=headers, json={"connector": "mission_sim", "permission": "read", "resource_ids": ["mission:read"], "domain_ids": ["dom_synthetic_a"], "expires_at": _expire()})
            http.post("/real/grants", headers=headers, json={"connector": "mission_sim", "permission": "read", "resource_ids": ["mission:write"], "domain_ids": ["dom_synthetic_a"], "expires_at": _expire()})
            review_grant = http.post("/real/grants", headers=headers, json={"connector": "mission_sim", "permission": "read", "resource_ids": ["mission:review"], "domain_ids": ["dom_synthetic_a"], "expires_at": _expire()})
            review_grant_id = review_grant.json()["id"]

            create_resp = http.post("/real/missions", headers=headers, json={"title": "Revogar no pause", "domain_id": "dom_synthetic_a", "idempotency_key": "rev-pause-create"})
            mission_id = create_resp.json()["mission"]["id"]
            http.post(f"/real/missions/{mission_id}/transition", headers=headers, json={"action": "run_next", "expected_revision": 1, "idempotency_key": "rev-pause-step"})

            review = http.get("/real/reviews", headers={"origin": ORIGIN}).json()["items"][0]
            review_id = review["id"]

            sink = []
            def decide():
                try:
                    res = http.post(
                        f"/real/reviews/{review_id}/decide",
                        headers=headers,
                        json={
                            "decision": "approved",
                            "expected_revision": 1,
                            "expected_artifact_sha256": review["artifact_sha256"],
                            "idempotency_key": "decide-pause-key",
                        },
                        timeout=8,
                    )
                    sink.append(res.status_code)
                except httpx.HTTPError as exc:
                    sink.append(type(exc).__name__)

            t = threading.Thread(target=decide)
            t.start()

            # Wait until checkpoint open
            d = time.time() + 10
            while time.time() < d:
                if pause.exists() and pause.read_text(encoding="utf-8") == "open":
                    break
                time.sleep(0.05)
            assert pause.exists() and pause.read_text(encoding="utf-8") == "open"

            # Revoke review grant while paused
            rev_res = http.post(f"/real/grants/{review_grant_id}/revoke", headers=headers)
            assert rev_res.status_code == 200

            # Release thread
            pause.write_text("go", encoding="utf-8")
            t.join(timeout=8)

            assert sink == [403]

            # Verify no decision was made
            final = http.get(f"/real/reviews/{review_id}", headers={"origin": ORIGIN}).json()
            assert final["state"] == "pending"
            assert final["history"] == []
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
