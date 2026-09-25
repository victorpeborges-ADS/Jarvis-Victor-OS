from __future__ import annotations

import os
import signal
import subprocess
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
