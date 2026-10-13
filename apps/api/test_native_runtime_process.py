from __future__ import annotations

import hashlib
import hmac
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from memory_store import SQLiteMemoryStore
from mission_repository import MissionRepository

PASSPHRASE = "senha-sintetica-processo-mac003"
SERVE = Path(__file__).with_name("serve.py")
PROTOCOL_VERSION = "3"
RUNTIME_KIND = "jarvis-synthetic"
BUILD_ID = "g6-mac-002-2-encrypted-uds-v3"
ENVELOPE_ROUTE = "/v3/secure"
ENVELOPE_VERSION = 3
APP_PATHS = {
    "/v1/app/session/open",
    "/v1/app/session/close",
    "/v1/app/grants/mission-read",
    "/v1/app/grants/mission-read/revoke",
    "/v1/app/missions/list",
    "/v1/app/captures/create",
    "/v1/app/captures/edit",
    "/v1/app/captures/delete",
    "/v1/app/captures/list",
    "/v1/app/captures/clear",
    "/v1/app/connectors/status",
    "/v1/app/grants/mission-review",
    "/v1/app/grants/mission-review/revoke",
    "/v1/app/reviews/pending",
    "/v1/app/reviews/draft",
    "/v1/app/reviews/detail",
    "/v1/app/reviews/approve",
    "/v1/app/workflows/submit",
    "/v1/app/workflows/list",
    "/v1/app/workflows/detail",
    "/v1/app/workflows/approve",
    "/v1/app/workflows/execute",
    "/v1/app/workflows/pause",
    "/v1/app/workflows/resume",
    "/v1/app/workflows/cancel",
    "/v1/app/automations/list",
    "/v1/app/automations/detail",
    "/v1/app/automations/history",
    "/v1/app/automations/run",
    "/v1/app/automations/create",
    "/v1/app/automations/timezone",
    "/v1/app/automations/control",
}


def _request(
    runtime_dir: Path,
    method: str,
    route: str,
    body: bytes = b"",
    *,
    content_type: str = "text/plain",
) -> tuple[int, bytes]:
    wire = (
        f"{method} {route} HTTP/1.1\r\n"
        "Host: jarvis.local\r\n"
        "Connection: close\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("ascii") + body
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(runtime_dir / "runtime.sock"))
        client.sendall(wire)
        response = bytearray()
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
    headers, payload = bytes(response).split(b"\r\n\r\n", 1)
    status = int(headers.split(b" ", 2)[1])
    return status, payload


def _fields(payload: bytes) -> dict[str, str]:
    return {
        name: unquote(value, encoding="utf-8", errors="strict")
        for name, value in (line.split("=", 1) for line in payload.decode("ascii").splitlines())
    }


def _body(**fields: str) -> bytes:
    return "".join(f"{name}={quote(value, safe='-_.~')}\n" for name, value in fields.items()).encode("ascii")


def _envelope_key(secret: bytes, purpose: bytes, direction: bytes, instance_id: str) -> bytes:
    context = (
        b"jarvis-local-envelope-v3\x00"
        + purpose
        + b"\x00"
        + direction
        + b"\x00"
        + instance_id.encode("ascii")
    )
    return hmac.new(secret, context, hashlib.sha256).digest()


def _envelope_mac_message(instance_id: str, direction: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    return (
        b"jarvis-local-envelope-v3\x00"
        + instance_id.encode("ascii")
        + b"\x00"
        + direction
        + b"\x00/v3/secure\x00"
        + nonce
        + ciphertext
    )


def _seal(secret: bytes, instance_id: str, direction: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    encryption_key = _envelope_key(secret, b"encryption", direction, instance_id)
    authentication_key = _envelope_key(secret, b"authentication", direction, instance_id)
    cipher = Cipher(algorithms.AES(encryption_key), modes.CTR(nonce)).encryptor()
    ciphertext = cipher.update(plaintext) + cipher.finalize()
    tag = hmac.new(
        authentication_key,
        _envelope_mac_message(instance_id, direction, nonce, ciphertext),
        hashlib.sha256,
    ).digest()
    return nonce + ciphertext + tag


def _open(secret: bytes, instance_id: str, direction: bytes, envelope: bytes) -> tuple[bytes, bytes]:
    nonce, ciphertext, tag = envelope[:16], envelope[16:-32], envelope[-32:]
    authentication_key = _envelope_key(secret, b"authentication", direction, instance_id)
    expected = hmac.new(
        authentication_key,
        _envelope_mac_message(instance_id, direction, nonce, ciphertext),
        hashlib.sha256,
    ).digest()
    assert hmac.compare_digest(tag, expected)
    encryption_key = _envelope_key(secret, b"encryption", direction, instance_id)
    cipher = Cipher(algorithms.AES(encryption_key), modes.CTR(nonce)).decryptor()
    return nonce, cipher.update(ciphertext) + cipher.finalize()


class _AuthenticatedRuntimeClient:
    def __init__(self, runtime_dir: Path, secret: bytes, instance_id: str):
        self.runtime_dir = runtime_dir
        self.secret = secret
        self.instance_id = instance_id
        self.sequence = 0

    def make_envelope(self, method: str, path: str, body: bytes = b"") -> bytes:
        assert method == "POST" and path in APP_PATHS
        self.sequence += 1
        nonce = self.sequence.to_bytes(8, "big") + bytes(8)
        path_bytes = path.encode("ascii")
        plaintext = (
            bytes([ENVELOPE_VERSION, 1])
            + len(path_bytes).to_bytes(2, "big")
            + len(body).to_bytes(4, "big")
            + path_bytes
            + body
        )
        return _seal(self.secret, self.instance_id, b"request", nonce, plaintext)

    def exchange_envelope(self, envelope: bytes) -> tuple[int, bytes]:
        return _request(
            self.runtime_dir,
            "POST",
            ENVELOPE_ROUTE,
            envelope,
            content_type="application/octet-stream",
        )

    def request(self, method: str, path: str, body: bytes = b"") -> tuple[int, bytes]:
        status, envelope = self.exchange_envelope(self.make_envelope(method, path, body))
        return self.decode_response(status, envelope)

    def decode_response(self, status: int, envelope: bytes) -> tuple[int, bytes]:
        if status != 200:
            return status, envelope
        nonce, plaintext = _open(self.secret, self.instance_id, b"response", envelope)
        assert len(plaintext) >= 7 and plaintext[0] == ENVELOPE_VERSION
        inner_status = int.from_bytes(plaintext[1:3], "big")
        body_length = int.from_bytes(plaintext[3:7], "big")
        assert len(plaintext) == body_length + 7
        return inner_status, plaintext[7:]


def _start_runtime(runtime_dir: Path, database_path: Path, instance_id: str) -> tuple[subprocess.Popen, bytes]:
    runtime_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(runtime_dir, 0o700)
    directory = runtime_dir.stat()
    secret = b"m" * 32
    child_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "JARVIS_LOCAL_PASSPHRASE": PASSPHRASE,
        "JARVIS_DATABASE_PATH": str(database_path),
    }
    process = subprocess.Popen(
        [sys.executable, "-u", str(SERVE), "--desktop-runtime", instance_id],
        cwd=runtime_dir,
        env=child_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdin is not None and process.stdout is not None
    init = (
        f"JARVIS_TRANSPORT_INIT {instance_id}\t{secret.hex()}\t"
        f"{directory.st_dev}\t{directory.st_ino}\n"
    ).encode("ascii")
    process.stdin.write(init)
    process.stdin.flush()
    ready, _, _ = select.select([process.stdout], [], [], 12)
    assert ready, "FastAPI did not reach supervised readiness"
    assert process.stdout.readline() == f"JARVIS_RUNTIME_READY {instance_id}\n".encode("ascii")
    process.stdin.write(f"JARVIS_RUNTIME_ACK {instance_id}\n".encode("ascii"))
    process.stdin.flush()
    return process, secret


def _stop(process: subprocess.Popen, instance_id: str) -> int:
    assert process.stdin is not None
    if process.poll() is None:
        process.stdin.write(f"JARVIS_RUNTIME_STOP {instance_id}\n".encode("ascii"))
        process.stdin.flush()
    return process.wait(timeout=4)


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires Unix domain sockets")
def test_supervised_fastapi_g5_vertical_flow_and_stop(tmp_path):
    runtime_storage = tempfile.TemporaryDirectory(prefix="jv-mac003-", dir="/tmp")
    runtime_dir = Path(runtime_storage.name) / "generation-1"
    database_path = tmp_path / "private" / "memory.sqlite3"
    seed_store = SQLiteMemoryStore(database_path)
    seed_store.initialize()
    seeded, _ = MissionRepository(seed_store).create(
        "owner", "Missão sintética via FastAPI", "dom_synthetic_a", "mac003-process-seed"
    )

    process, secret = _start_runtime(runtime_dir, database_path, "native-process-generation-1")
    try:
        status, health = _request(runtime_dir, "GET", "/v1/health")
        assert status == 200 and health == b"ok\n"
        status, version = _request(runtime_dir, "GET", "/v1/version")
        assert status == 200
        assert _fields(version) == {
            "protocol_version": PROTOCOL_VERSION,
            "runtime_kind": RUNTIME_KIND,
            "instance_id": "native-process-generation-1",
            "build": BUILD_ID,
        }

        nonce = "ab" * 32
        status, proof = _request(runtime_dir, "POST", "/v1/instance-proof", nonce.encode("ascii"))
        proof_fields = _fields(proof)
        message = (
            "jarvis-local-transport-proof-v3\n"
            f"{PROTOCOL_VERSION}\n{RUNTIME_KIND}\n"
            "native-process-generation-1\n"
            f"{BUILD_ID}\n{nonce}\n"
            "pong:native-process-generation-1"
        ).encode("ascii")
        assert status == 200
        assert hmac.compare_digest(
            proof_fields["proof"], hmac.new(secret, message, hashlib.sha256).hexdigest()
        )

        # Plain same-UID clients cannot invoke application routes without the generation capability.
        direct_status, _ = _request(
            runtime_dir,
            "POST",
            "/v1/app/session/open",
            _body(passphrase=PASSPHRASE),
        )
        assert direct_status == 404
        wrong_client = _AuthenticatedRuntimeClient(
            runtime_dir, b"x" * 32, "native-process-generation-1"
        )
        wrong_status, _ = wrong_client.request(
            "POST",
            "/v1/app/session/open",
            _body(passphrase="passphrase-sintetica-incorreta"),
        )
        assert wrong_status == 401

        replay_client = _AuthenticatedRuntimeClient(
            runtime_dir, secret, "native-process-generation-1"
        )
        replay_envelope = replay_client.make_envelope(
            "POST",
            "/v1/app/session/open",
            _body(passphrase="passphrase-sintetica-incorreta"),
        )
        first_status, first_envelope = replay_client.exchange_envelope(replay_envelope)
        assert first_status == 200
        replay_client.decode_response(first_status, first_envelope)
        replay_status, _ = replay_client.exchange_envelope(replay_envelope)
        assert replay_status == 409

        client = replay_client

        status, opened = client.request(
            "POST",
            "/v1/app/session/open",
            _body(passphrase=PASSPHRASE),
        )
        assert status == 200
        session = _fields(opened)
        assert session["ok"] == "true" and session["principal"] == "owner"
        assert PASSPHRASE not in opened.decode("ascii")

        status, empty_automations = client.request(
            "POST", "/v1/app/automations/list",
            _body(session_token=session["session_token"]),
        )
        assert status == 200
        assert _fields(empty_automations) == {"ok": "true", "items": "", "count": "0"}

        status, created = client.request(
            "POST", "/v1/app/automations/create",
            _body(
                session_token=session["session_token"], csrf_token=session["csrf_token"],
                kind="reminder", title="Lembrete de processo", recurrence="once",
                local_schedule="2099-01-01T09:00", timezone="UTC",
                quiet_start="", quiet_end="", message="Rascunho local sintético",
                sources_confirmed="none",
            ),
        )
        created_fields = _fields(created)
        assert status == 200 and created_fields["ok"] == "true"
        assert created_fields["workflow_version"] == "reminder.v1"
        status, listed_automations = client.request(
            "POST", "/v1/app/automations/list",
            _body(session_token=session["session_token"]),
        )
        listed_fields = _fields(listed_automations)
        assert status == 200 and listed_fields["count"] == "1"
        assert created_fields["id"] in listed_fields["items"]

        status, denied = client.request(
            "POST",
            "/v1/app/missions/list",
            _body(session_token=session["session_token"], domain_id="dom_synthetic_a"),
        )
        assert status == 200 and _fields(denied) == {"ok": "false", "code": "grant_required"}

        status, grant_response = client.request(
            "POST",
            "/v1/app/grants/mission-read",
            _body(
                session_token=session["session_token"],
                csrf_token=session["csrf_token"],
                domain_id="dom_synthetic_a",
            ),
        )
        grant = _fields(grant_response)
        assert status == 200 and grant["ok"] == "true"
        assert grant["domain_id"] == "dom_synthetic_a"

        status, read_response = client.request(
            "POST",
            "/v1/app/missions/list",
            _body(session_token=session["session_token"], domain_id="dom_synthetic_a"),
        )
        mission = _fields(read_response)
        assert status == 200
        assert mission == {
            "ok": "true",
            "dataset": "api_synthetic",
            "count": "1",
            "mission_id": seeded["mission"]["id"],
            "title": "Missão sintética via FastAPI",
            "domain_id": "dom_synthetic_a",
            "status": "planned",
            "revision": "1",
        }

        status, revoked = client.request(
            "POST",
            "/v1/app/grants/mission-read/revoke",
            _body(
                session_token=session["session_token"],
                csrf_token=session["csrf_token"],
                grant_id=grant["grant_id"],
            ),
        )
        assert status == 200 and _fields(revoked) == {"ok": "true", "revoked": "true"}

        status, closed = client.request(
            "POST",
            "/v1/app/session/close",
            _body(session_token=session["session_token"], csrf_token=session["csrf_token"]),
        )
        assert status == 200 and _fields(closed) == {"ok": "true", "closed": "true"}

        if shutil.which("lsof"):
            listeners = subprocess.run(
                ["lsof", "-Pan", "-p", str(process.pid), "-i"],
                check=False,
                capture_output=True,
                text=True,
            )
            assert not any("LISTEN" in line for line in listeners.stdout.splitlines())
    finally:
        assert _stop(process, "native-process-generation-1") == 0
        assert process.poll() is not None
        runtime_storage.cleanup()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires Unix domain sockets")
def test_supervisor_eof_stops_fastapi_process(tmp_path):
    runtime_storage = tempfile.TemporaryDirectory(prefix="jv-mac003-", dir="/tmp")
    runtime_dir = Path(runtime_storage.name) / "generation-eof"
    database_path = tmp_path / "private" / "eof.sqlite3"
    process, _ = _start_runtime(runtime_dir, database_path, "native-process-generation-eof")
    assert process.stdin is not None
    process.stdin.close()
    assert process.wait(timeout=4) == 48
    assert process.poll() is not None
    runtime_storage.cleanup()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires Unix domain sockets")
def test_fastapi_crash_can_be_replaced_by_a_new_generation(tmp_path):
    runtime_storage = tempfile.TemporaryDirectory(prefix="jv-mac003-", dir="/tmp")
    root = Path(runtime_storage.name)
    crashed, _ = _start_runtime(root / "generation-crash", tmp_path / "private" / "crash.sqlite3", "native-crash-generation")
    crashed.kill()
    assert crashed.wait(timeout=4) < 0

    restarted, _ = _start_runtime(root / "generation-restart", tmp_path / "private" / "restart.sqlite3", "native-restart-generation")
    try:
        status, health = _request(root / "generation-restart", "GET", "/v1/health")
        assert status == 200 and health == b"ok\n"
    finally:
        assert _stop(restarted, "native-restart-generation") == 0
        runtime_storage.cleanup()
