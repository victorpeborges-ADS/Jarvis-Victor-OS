"""Selected synthetic files stay staged through both human review gates."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backup_recovery import create_backup, restore_backup
from local_security import Grant, put_grant_for_tests, put_session_for_tests
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


def _body():
    content = "Dado fictício para testar a seleção manual.\n"
    return {"display_name": "nota-ficticia.md", "content": content,
            "expected_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "idempotency_key": "selected-source-key", "confirm_synthetic": True}


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
    assert review["artifact"]["content"] == body["content"]
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
    assert len(included) == 1 and included[0]["content"] == body["content"]
    assert included[0]["source_review_id"] == source["review_id"]
    final_status = client.get(path, headers={"origin": ORIGIN}).json()["items"][0]
    assert final_status["artifact_review_state"] == "approved"
    assert final_status["knowledge_state"] == "approved"
    archive = create_backup(client.database_path, tmp_path / "backups", "senha-sintetica-arquivo-selecionado")
    restored = restore_backup(archive, tmp_path / "restore", "senha-sintetica-arquivo-selecionado")
    with sqlite3.connect(restored) as con:
        assert con.execute("SELECT COUNT(*) FROM selected_synthetic_sources").fetchone()[0] == 1
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_selected_source_rejects_bad_input_and_duplicate_key(client):
    csrf = login(client)
    mission_all_grants(client, csrf)
    mission_id = _mission(client, csrf)
    path = f"/real/missions/{mission_id}/sources"
    good = _body()
    for patch, expected in [
        ({"confirm_synthetic": False}, 422),
        ({"display_name": "../secret.md"}, 422),
        ({"display_name": "secret.pdf"}, 422),
        ({"expected_content_sha256": "0" * 64}, 409),
        ({"content": "x" * 50001}, 422),
    ]:
        assert client.post(path, headers=_headers(csrf), json={**good, **patch}).status_code == expected
    assert client.get(path, headers={"origin": ORIGIN}).json()["items"] == []
    assert client.post(path, headers=_headers(csrf), json=good).status_code == 201
    assert client.post(path, headers=_headers(csrf), json={**good, "display_name": "outro.md"}).status_code == 409


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
