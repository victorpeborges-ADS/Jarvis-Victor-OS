"""G4 writes must obey the same live session/grant boundary as G5 decisions."""

import sqlite3
import threading
import time

import pytest

import local_security
import mission_api
from test_review_api import ORIGIN, client, login, mission_all_grants


def _headers(csrf):
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def _create(client, csrf, key):
    response = client.post("/real/missions", headers=_headers(csrf), json={
        "title": "Corrida de autorização fictícia", "domain_id": "dom_synthetic_a",
        "idempotency_key": key,
    })
    assert response.status_code == 201, response.text
    return response.json()["mission"]["id"]


@pytest.mark.parametrize("interruption", ["logout", "revoke"])
def test_run_does_not_commit_after_session_or_write_grant_revoked(client, monkeypatch, tmp_path, interruption):
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    mission_id = _create(client, csrf, f"create-paused-{interruption}")
    pause = tmp_path / "run-pause.txt"
    monkeypatch.setenv("JARVIS_TEST_PAUSE_FILE", str(pause))
    result = []

    def run():
        result.append(client.post(f"/real/missions/{mission_id}/transition", headers=_headers(csrf), json={
            "action": "run_next", "expected_revision": 1,
            "idempotency_key": f"paused-run-{interruption}",
        }))

    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (not pause.exists() or pause.read_text() != "open"):
            time.sleep(0.02)
        assert pause.exists() and pause.read_text() == "open"
        if interruption == "logout":
            changed = client.delete("/real/session", headers=_headers(csrf))
            assert changed.status_code == 204, changed.text
        else:
            changed = client.post(f"/real/grants/{grants['write']}/revoke", headers=_headers(csrf), json={})
            assert changed.status_code == 200, changed.text
        pause.write_text("go")
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert result[0].status_code == 403, result[0].text
        with sqlite3.connect(client.database_path) as connection:
            record = connection.execute("SELECT document_json, status FROM missions WHERE id=?", (mission_id,)).fetchone()
            assert record[1] == "interrupted"
            assert connection.execute("SELECT COUNT(*) FROM mission_artifact_reviews WHERE mission_id=?", (mission_id,)).fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM mission_knowledge WHERE mission_id=?", (mission_id,)).fetchone()[0] == 0
    finally:
        if worker.is_alive():
            pause.write_text("go")
            worker.join(timeout=5)


def test_create_rechecks_write_grant_after_route_precheck(client, monkeypatch):
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    original = mission_api._require

    def revoke_after_precheck(principal, resource, domain):
        original(principal, resource, domain)
        if resource == "mission:write":
            local_security._grants[grants["write"]].revoked = True

    monkeypatch.setattr(mission_api, "_require", revoke_after_precheck)
    response = client.post("/real/missions", headers=_headers(csrf), json={
        "title": "Não criar após revoke", "domain_id": "dom_synthetic_a",
        "idempotency_key": "create-revoked-after-precheck",
    })
    assert response.status_code == 403, response.text
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM missions").fetchone()[0] == 0


def test_direct_transition_rechecks_write_grant_after_route_precheck(client, monkeypatch):
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    mission_id = _create(client, csrf, "create-before-direct-revoke")
    original = mission_api._require

    def revoke_after_precheck(principal, resource, domain):
        original(principal, resource, domain)
        if resource == "mission:write":
            local_security._grants[grants["write"]].revoked = True

    monkeypatch.setattr(mission_api, "_require", revoke_after_precheck)
    response = client.post(f"/real/missions/{mission_id}/transition", headers=_headers(csrf), json={
        "action": "cancel", "expected_revision": 1, "idempotency_key": "cancel-revoked-after-precheck",
    })
    assert response.status_code == 403, response.text
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT status FROM missions WHERE id=?", (mission_id,)).fetchone()[0] == "planned"


def test_import_rechecks_write_grant_after_filter(client, monkeypatch):
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    mission_id = _create(client, csrf, "create-before-import-revoke")
    document = client.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()["mission"]
    original = mission_api.mission_domains

    def revoke_after_filter(principal, resource):
        domains = original(principal, resource)
        if resource == "mission:write":
            local_security._grants[grants["write"]].revoked = True
        return domains

    monkeypatch.setattr(mission_api, "mission_domains", revoke_after_filter)
    response = client.post("/real/missions/import", headers=_headers(csrf), json={
        "missions": [document], "idempotency_key": "import-revoked-after-filter", "confirm": True,
    })
    assert response.status_code == 403, response.text
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mission_idempotency WHERE idempotency_key=?",
                                  ("import-revoked-after-filter",)).fetchone()[0] == 0
