from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

PASSPHRASE = "senha-sintetica-de-missao"
ORIGIN = "http://127.0.0.1:3000"
ROOT = Path(__file__).resolve().parent


def _expire() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def test_sigkill_during_open_step_requires_authorized_resume(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    database = private / "memory.sqlite3"
    pause = tmp_path / "pause.txt"
    port = 18771
    env = os.environ.copy()
    env.update({
        "JARVIS_BIND_HOST": "127.0.0.1",
        "JARVIS_BIND_PORT": str(port),
        "JARVIS_DATABASE_PATH": str(database),
        "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE,
        "JARVIS_TEST_PAUSE_FILE": str(pause),
    })
    python = ROOT / ".venv" / "bin" / "python"

    def start():
        return subprocess.Popen(
            [str(python), "serve.py"], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
        )

    def ready(proc, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                raise AssertionError(proc.stderr.read().decode()[-500:])
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.4).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise AssertionError("api de teste não subiu")

    proc = start()
    try:
        ready(proc)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as http:
            login = http.post("/real/session", json={"passphrase": PASSPHRASE}, headers={"origin": ORIGIN})
            csrf = login.json()["csrf_token"]
            headers = {"origin": ORIGIN, "x-csrf-token": csrf}
            for resource in ("mission:read", "mission:write"):
                assert http.post("/real/grants", headers=headers, json={
                    "connector": "mission_sim", "permission": "read", "resource_ids": [resource],
                    "domain_ids": ["dom_synthetic_a"], "expires_at": _expire(),
                }).status_code == 201
            created = http.post("/real/missions", headers=headers, json={
                "title": "interromper sem duplicar", "domain_id": "dom_synthetic_a", "idempotency_key": "kill-create-01",
            })
            mission_id = created.json()["mission"]["id"]

            def blocked_step():
                try:
                    http.post(
                        f"/real/missions/{mission_id}/transition",
                        headers=headers,
                        json={"action": "run_next", "expected_revision": 1, "idempotency_key": "kill-run-01"},
                        timeout=5,
                    )
                except httpx.HTTPError:
                    return

            import threading
            worker = threading.Thread(target=blocked_step)
            worker.start()
            deadline = time.time() + 10
            while time.time() < deadline:
                if pause.exists() and pause.read_text(encoding="utf-8") == "open":
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("a execução não chegou a abrir")
            assert pause.read_text(encoding="utf-8") == "open"
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        worker.join(timeout=2)
        env.pop("JARVIS_TEST_PAUSE_FILE")
        proc = start()
        ready(proc)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as http:
            login = http.post("/real/session", json={"passphrase": PASSPHRASE}, headers={"origin": ORIGIN})
            csrf = login.json()["csrf_token"]
            headers = {"origin": ORIGIN, "x-csrf-token": csrf}
            for resource in ("mission:read", "mission:write"):
                http.post("/real/grants", headers=headers, json={
                    "connector": "mission_sim", "permission": "read", "resource_ids": [resource],
                    "domain_ids": ["dom_synthetic_a"], "expires_at": _expire(),
                })
            loaded = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
            body = loaded.json()
            assert body["mission"]["status"] == "interrupted"
            assert body["mission"]["artifacts"] == []
            assert "resume" in body["available_actions"]
            resumed = http.post(
                f"/real/missions/{mission_id}/transition",
                headers=headers,
                json={"action": "resume", "expected_revision": body["revision"], "idempotency_key": "kill-resume-1"},
            )
            assert resumed.status_code == 200, resumed.text
            assert len(resumed.json()["mission"]["artifacts"]) == 1
            again = http.post(
                f"/real/missions/{mission_id}/transition",
                headers=headers,
                json={"action": "resume", "expected_revision": resumed.json()["revision"], "idempotency_key": "kill-resume-2"},
            )
            assert again.status_code == 422
            reread = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
            assert len(reread.json()["mission"]["artifacts"]) == 1
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def _server(tmp_path: Path, port: int, pause: Path | None):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    database = private / "memory.sqlite3"
    env = os.environ.copy()
    env.update({
        "JARVIS_BIND_HOST": "127.0.0.1",
        "JARVIS_BIND_PORT": str(port),
        "JARVIS_DATABASE_PATH": str(database),
        "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE,
    })
    if pause is not None:
        env["JARVIS_TEST_PAUSE_FILE"] = str(pause)
    else:
        env.pop("JARVIS_TEST_PAUSE_FILE", None)
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "python"), "serve.py"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(proc.stderr.read().decode()[-500:])
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.4).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    os.killpg(proc.pid, signal.SIGKILL)
    raise AssertionError("api de teste não subiu")


def _auth(http: httpx.Client):
    login = http.post("/real/session", json={"passphrase": PASSPHRASE}, headers={"origin": ORIGIN})
    csrf = login.json()["csrf_token"]
    headers = {"origin": ORIGIN, "x-csrf-token": csrf}
    ids = {}
    for resource in ("mission:read", "mission:write"):
        created = http.post("/real/grants", headers=headers, json={
            "connector": "mission_sim", "permission": "read", "resource_ids": [resource],
            "domain_ids": ["dom_synthetic_a"], "expires_at": _expire(),
        })
        assert created.status_code == 201, created.text
        ids[resource] = created.json()["id"]
    return headers, ids


def _wait_open(pause: Path) -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        if pause.exists() and pause.read_text(encoding="utf-8") == "open":
            return
        time.sleep(0.05)
    raise AssertionError("checkpoint não abriu")


def _stop(proc) -> None:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


def _mission(http: httpx.Client, headers: dict, title: str, key: str) -> str:
    created = http.post("/real/missions", headers=headers, json={
        "title": title, "domain_id": "dom_synthetic_a", "idempotency_key": key,
    })
    assert created.status_code == 201, created.text
    return created.json()["mission"]["id"]


def _transition(base: str, headers: dict, cookies, mission_id: str, body: dict) -> httpx.Response:
    with httpx.Client(base_url=base, timeout=15, cookies=dict(cookies)) as client:
        return client.post(f"/real/missions/{mission_id}/transition", headers=headers, json=body)


def _spawn(base: str, headers: dict, cookies, mission_id: str, body: dict, sink: list) -> threading.Thread:
    def work() -> None:
        try:
            response = _transition(base, headers, cookies, mission_id, body)
            sink.append(response.status_code)
        except Exception as exc:
            sink.append(type(exc).__name__)

    thread = threading.Thread(target=work)
    thread.start()
    return thread


def test_cancel_confirmed_before_skill_prevents_artifact(tmp_path):
    port = 18791
    pause = tmp_path / "pause.txt"
    proc = _server(tmp_path, port, pause)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, _ids = _auth(http)
            mission_id = _mission(http, headers, "cancelar antes do commit", "r1-cancel-create")
            sink: list = []
            worker = _spawn(base, headers, http.cookies, mission_id, {
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-cancel-run",
            }, sink)
            _wait_open(pause)
            cancelled = http.post(f"/real/missions/{mission_id}/transition", headers=headers, json={
                "action": "cancel", "expected_revision": 1, "idempotency_key": "r1-cancel-now",
            })
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["mission"]["status"] == "cancelled"
            pause.write_text("go", encoding="utf-8")
            worker.join(timeout=12)
            assert sink == [409]
            final = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
            assert final.json()["mission"]["status"] == "cancelled"
            assert final.json()["mission"]["artifacts"] == []
    finally:
        _stop(proc)


def test_revoked_write_grant_before_commit_requires_new_grant_to_resume(tmp_path):
    port = 18792
    pause = tmp_path / "pause.txt"
    proc = _server(tmp_path, port, pause)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, ids = _auth(http)
            mission_id = _mission(http, headers, "revogar antes do commit", "r1-revoke-create")
            sink: list = []
            worker = _spawn(base, headers, http.cookies, mission_id, {
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-revoke-run",
            }, sink)
            _wait_open(pause)
            revoked = http.post(f"/real/grants/{ids['mission:write']}/revoke", headers=headers)
            assert revoked.status_code == 200
            pause.write_text("go", encoding="utf-8")
            worker.join(timeout=12)
            assert sink == [403]
            final = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
            assert final.json()["mission"]["artifacts"] == []
            assert final.json()["mission"]["status"] == "interrupted"
            denied_sink: list = []
            denied_worker = _spawn(base, headers, http.cookies, mission_id, {
                "action": "resume", "expected_revision": final.json()["revision"], "idempotency_key": "r1-resume-denied",
            }, denied_sink)
            denied_worker.join(timeout=8)
            assert denied_sink == [403]
            renewed = http.post("/real/grants", headers=headers, json={
                "connector": "mission_sim", "permission": "read", "resource_ids": ["mission:write"],
                "domain_ids": ["dom_synthetic_a"], "expires_at": _expire(),
            })
            assert renewed.status_code == 201, renewed.text
            resume_sink: list = []
            resume_worker = _spawn(base, headers, http.cookies, mission_id, {
                "action": "resume", "expected_revision": final.json()["revision"], "idempotency_key": "r1-resume-ok",
            }, resume_sink)
            _wait_open(pause)
            pause.write_text("go", encoding="utf-8")
            resume_worker.join(timeout=12)
            assert resume_sink == [200]
            resumed = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
            assert len(resumed["mission"]["artifacts"]) == 1
            again_sink: list = []
            again_worker = _spawn(base, headers, http.cookies, mission_id, {
                "action": "resume", "expected_revision": resumed["revision"], "idempotency_key": "r1-resume-again",
            }, again_sink)
            again_worker.join(timeout=8)
            assert again_sink == [422]
            reread = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
            assert len(reread.json()["mission"]["artifacts"]) == 1
            assert reread.json()["mission"]["status"] == "running"
    finally:
        _stop(proc)


def test_expired_write_grant_before_commit_prevents_artifact(tmp_path):
    port = 18793
    pause = tmp_path / "pause.txt"
    proc = _server(tmp_path, port, pause)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, _ids = _auth(http)
            mission_id = _mission(http, headers, "expirar antes do commit", "r1-expire-create")
            revoked = http.post(f"/real/grants/{_ids['mission:write']}/revoke", headers=headers)
            assert revoked.status_code == 200
            short = http.post("/real/grants", headers=headers, json={
                "connector": "mission_sim", "permission": "read", "resource_ids": ["mission:write"],
                "domain_ids": ["dom_synthetic_a"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=4)).isoformat(),
            })
            assert short.status_code == 201, short.text
            sink: list = []
            worker = _spawn(base, headers, http.cookies, mission_id, {
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-expire-run",
            }, sink)
            _wait_open(pause)
            time.sleep(4.5)
            pause.write_text("go", encoding="utf-8")
            worker.join(timeout=12)
            assert sink == [403]
            final = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN})
            assert final.json()["mission"]["artifacts"] == []
            assert final.json()["mission"]["status"] == "interrupted"
    finally:
        _stop(proc)


def test_commit_before_cancel_keeps_artifact_and_stale_cancel_conflicts(tmp_path):
    port = 18794
    proc = _server(tmp_path, port, None)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, _ids = _auth(http)
            mission_id = _mission(http, headers, "commit antes do cancelamento", "r1-commit-first-create")
            ran = http.post(f"/real/missions/{mission_id}/transition", headers=headers, json={
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-commit-first-run",
            })
            assert ran.status_code == 200, ran.text
            assert len(ran.json()["mission"]["artifacts"]) == 1
            stale = http.post(f"/real/missions/{mission_id}/transition", headers=headers, json={
                "action": "cancel", "expected_revision": 1, "idempotency_key": "r1-commit-first-stale",
            })
            assert stale.status_code == 409
            current = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
            assert current["mission"]["status"] == "running"
            assert len(current["mission"]["artifacts"]) == 1
            cancelled = http.post(f"/real/missions/{mission_id}/transition", headers=headers, json={
                "action": "cancel", "expected_revision": current["revision"], "idempotency_key": "r1-commit-first-cancel",
            })
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["mission"]["status"] == "cancelled"
            assert len(cancelled.json()["mission"]["artifacts"]) == 1
            late = http.post(f"/real/missions/{mission_id}/transition", headers=headers, json={
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-commit-first-late",
            })
            assert late.status_code == 409
            final = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
            assert final["mission"]["status"] == "cancelled"
            assert len(final["mission"]["artifacts"]) == 1
    finally:
        _stop(proc)


def test_concurrent_cancel_and_run_have_one_winner(tmp_path):
    port = 18795
    proc = _server(tmp_path, port, None)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, _ids = _auth(http)
            mission_id = _mission(http, headers, "corrida commit e cancelamento", "r1-race-create")
            run_sink: list = []
            cancel_sink: list = []
            runner = _spawn(base, headers, http.cookies, mission_id, {
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-race-run",
            }, run_sink)
            canceller = _spawn(base, headers, http.cookies, mission_id, {
                "action": "cancel", "expected_revision": 1, "idempotency_key": "r1-race-cancel",
            }, cancel_sink)
            runner.join(timeout=12)
            canceller.join(timeout=12)
            assert run_sink in ([200], [409], [422])
            assert cancel_sink in ([200], [409])
            assert not (run_sink == [200] and cancel_sink == [200])
            final = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
            if cancel_sink == [200]:
                assert final["mission"]["status"] == "cancelled"
                assert final["mission"]["artifacts"] == []
            else:
                assert run_sink == [200]
                assert final["mission"]["status"] == "running"
                assert len(final["mission"]["artifacts"]) == 1
    finally:
        _stop(proc)


def test_two_concurrent_runs_commit_one_artifact(tmp_path):
    port = 18796
    pause = tmp_path / "pause.txt"
    proc = _server(tmp_path, port, pause)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, _ids = _auth(http)
            mission_id = _mission(http, headers, "duas execuções", "r1-two-create")
            first: list = []
            second: list = []
            left = _spawn(base, headers, http.cookies, mission_id, {
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-two-a",
            }, first)
            _wait_open(pause)
            right = _spawn(base, headers, http.cookies, mission_id, {
                "action": "run_next", "expected_revision": 1, "idempotency_key": "r1-two-b",
            }, second)
            right.join(timeout=8)
            pause.write_text("go", encoding="utf-8")
            left.join(timeout=12)
            assert first == [200]
            assert second in ([409], [422])
            final = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
            assert len(final["mission"]["artifacts"]) == 1
            assert final["mission"]["status"] == "running"
    finally:
        _stop(proc)


def test_stale_revision_does_not_start_or_invent_progress(tmp_path):
    port = 18797
    proc = _server(tmp_path, port, None)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, _ids = _auth(http)
            mission_id = _mission(http, headers, "revisão obsoleta", "r1-stale-create")
            stale = http.post(f"/real/missions/{mission_id}/transition", headers=headers, json={
                "action": "run_next", "expected_revision": 7, "idempotency_key": "r1-stale-run",
            })
            assert stale.status_code == 409
            final = http.get(f"/real/missions/{mission_id}", headers={"origin": ORIGIN}).json()
            assert final["mission"]["status"] == "planned"
            assert final["mission"]["artifacts"] == []
            assert final["revision"] == 1
    finally:
        _stop(proc)


def test_mission_and_calendar_grants_stay_isolated(tmp_path):
    port = 18798
    proc = _server(tmp_path, port, None)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=8) as http:
            headers, ids = _auth(http)
            events = http.get("/real/events", headers={"origin": ORIGIN})
            assert events.status_code == 403
            for grant_id in ids.values():
                revoked = http.post(f"/real/grants/{grant_id}/revoke", headers=headers)
                assert revoked.status_code == 200
            calendar = http.post("/real/grants", headers=headers, json={
                "connector": "calendar_sim", "permission": "read", "resource_ids": ["calendar:synthetic-primary"],
                "domain_ids": ["dom_synthetic_a"], "expires_at": _expire(),
            })
            assert calendar.status_code == 201, calendar.text
            denied = http.post("/real/missions", headers=headers, json={
                "title": "calendar não cria missão", "domain_id": "dom_synthetic_a", "idempotency_key": "r1-cal-no-mission",
            })
            assert denied.status_code == 403
    finally:
        _stop(proc)
