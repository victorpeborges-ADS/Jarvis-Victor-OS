"""Adversarial read/revoke order probes for mission and review snapshots."""

from __future__ import annotations

import threading
from contextlib import closing, contextmanager

import pytest
from fastapi.testclient import TestClient

from mission_repository import MissionRepository
import knowledge_api
import selected_source_api
from test_review_api import ORIGIN, client, create_and_run_step, login, mission_all_grants


_READS = {
    "mission_detail": ("get", "mission:read"),
    "mission_list": ("list_page", "mission:read"),
    "review_detail": ("get_review", "mission:review"),
    "review_list": ("list_reviews", "mission:review"),
    "source_list": ("source_read", "mission:read"),
    "knowledge_list": ("knowledge_read", "mission:read"),
}


def _headers(csrf: str) -> dict[str, str]:
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def _get_path(kind: str, mission_id: str, review_id: str) -> str:
    if kind == "mission_detail":
        return f"/real/missions/{mission_id}"
    if kind == "mission_list":
        return "/real/missions?domain_id=dom_synthetic_a"
    if kind == "review_detail":
        return f"/real/reviews/{review_id}"
    if kind == "source_list":
        return f"/real/missions/{mission_id}/sources"
    if kind == "knowledge_list":
        return "/real/knowledge"
    return "/real/reviews?domain_id=dom_synthetic_a"


def _prepare(client, kind: str) -> tuple[str, str, str, str]:
    csrf = login(client)
    grants = mission_all_grants(client, csrf)
    mission, review_id = create_and_run_step(client, csrf, f"Leitura sob revoke {kind}")
    if _READS[kind][1] == "mission:review":
        # A review-only grant must be the scope that authorizes this read.
        revoked = client.post(f"/real/grants/{grants['read']}/revoke", headers=_headers(csrf))
        assert revoked.status_code == 200, revoked.text
        grant_id = grants["review"]
    else:
        grant_id = grants["read"]
    mission_id = mission["mission"]["id"]
    if kind in {"source_list", "knowledge_list"}:
        selected = client.post(f"/real/missions/{mission_id}/sources", headers=_headers(csrf), json={
            "fixture_id": "tarefas-de-exemplo", "idempotency_key": f"race-source-{kind}",
        })
        assert selected.status_code == 201, selected.text
    return csrf, _get_path(kind, mission_id, review_id), grant_id, review_id


def _client_with_session(parent: TestClient, port: int) -> TestClient:
    child = TestClient(parent.app, base_url="http://127.0.0.1", client=("127.0.0.1", port))
    child.cookies.set("jarvis_session", parent.cookies.get("jarvis_session"))
    return child


@pytest.mark.parametrize("kind", list(_READS))
def test_read_snapshot_wins_then_revoke_waits_for_assembly(client, monkeypatch, kind):
    csrf, path, grant_id, review_id = _prepare(client, kind)
    method_name, _ = _READS[kind]
    source_read_module = selected_source_api if kind == "source_list" else knowledge_api if kind == "knowledge_list" else None
    original = (source_read_module.mission_read_confirmed if source_read_module is not None
                else getattr(MissionRepository, method_name))
    entered_read = threading.Event()
    release_read = threading.Event()
    revoke_started = threading.Event()
    revoke_done = threading.Event()
    responses: dict[str, object] = {}

    if source_read_module is not None:
        @contextmanager
        def paused_grant(*args, **kwargs):
            with original(*args, **kwargs):
                entered_read.set()
                if not release_read.wait(timeout=10):
                    raise RuntimeError("probe de leitura excedeu o tempo de pausa")
                yield
        monkeypatch.setattr(source_read_module, "mission_read_confirmed", paused_grant)
    else:
        def paused(self, *args, **kwargs):
            record_id = args[1] if len(args) > 1 and method_name in {"get", "get_review"} else None
            if record_id is None or record_id == review_id or kind.startswith("mission"):
                entered_read.set()
                if not release_read.wait(timeout=10):
                    raise RuntimeError("probe de leitura excedeu o tempo de pausa")
            return original(self, *args, **kwargs)
        monkeypatch.setattr(MissionRepository, method_name, paused)

    def read_request():
        with closing(_client_with_session(client, 50997)) as reader:
            responses["read"] = reader.get(path, headers={"origin": ORIGIN})

    def revoke_request():
        revoke_started.set()
        with closing(_client_with_session(client, 50998)) as revoker:
            responses["revoke"] = revoker.post(
                f"/real/grants/{grant_id}/revoke", headers=_headers(csrf)
            )
        revoke_done.set()

    reader = threading.Thread(target=read_request)
    revoker = threading.Thread(target=revoke_request)
    reader.start()
    try:
        assert entered_read.wait(timeout=5), "a leitura não chegou à montagem do snapshot"
        revoker.start()
        assert revoke_started.wait(timeout=5)
        assert not revoke_done.wait(timeout=0.2), "revogação ultrapassou a leitura já linearizada"
        release_read.set()
        reader.join(timeout=10)
        revoker.join(timeout=10)
        assert not reader.is_alive()
        assert not revoker.is_alive()
        assert responses["read"].status_code == 200, responses["read"].text
        assert responses["revoke"].status_code == 200, responses["revoke"].text
    finally:
        release_read.set()
        reader.join(timeout=5)
        if revoker.ident is not None:
            revoker.join(timeout=5)


@pytest.mark.parametrize("kind", list(_READS))
def test_revoke_wins_then_mission_or_review_read_fails_closed(client, kind):
    csrf, path, grant_id, _ = _prepare(client, kind)
    if kind.startswith("review"):
        # Remove the remaining review grant after the read grant was removed in _prepare.
        revoked_review = client.post(f"/real/grants/{grant_id}/revoke", headers=_headers(csrf))
        assert revoked_review.status_code == 200, revoked_review.text
        response = client.get(path, headers={"origin": ORIGIN})
    else:
        revoked_read = client.post(f"/real/grants/{grant_id}/revoke", headers=_headers(csrf))
        assert revoked_read.status_code == 200, revoked_read.text
        response = client.get(path, headers={"origin": ORIGIN})
    assert response.status_code == 403, response.text
