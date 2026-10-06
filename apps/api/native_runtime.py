"""Private UDS routes and framing for the supervised FastAPI runtime."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

PROTOCOL_VERSION = "1"
RUNTIME_KIND = "jarvis-synthetic"
BUILD_ID = "g6-mac-003-fastapi-g5-v1"
INIT_PREFIX = b"JARVIS_TRANSPORT_INIT "
INIT_MAX_BYTES = 1024
APP_REQUEST_MAX_BYTES = 1024
CONTROL_REQUEST_MAX_BYTES = 128
MAX_REQUEST_HEADER_BYTES = 1024
REQUEST_BODY_TIMEOUT_SECONDS = 0.9
APP_PATHS = frozenset(
    {
        ("POST", "/v1/app/session/open"),
        ("POST", "/v1/app/session/close"),
        ("POST", "/v1/app/grants/mission-read"),
        ("POST", "/v1/app/grants/mission-read/revoke"),
        ("POST", "/v1/app/missions/list"),
    }
)
CONTROL_PATHS = frozenset(
    {
        ("GET", "/v1/health"),
        ("GET", "/v1/version"),
        ("POST", "/v1/instance-proof"),
    }
)
ALLOWED_HEADERS = frozenset({b"host", b"content-type", b"content-length", b"connection"})


@dataclass
class NativeRuntimeIdentity:
    instance_id: str
    secret: bytearray = field(repr=False)
    directory_dev: int
    directory_ino: int
    acknowledged: Event = field(default_factory=Event, repr=False)

    def clear(self) -> None:
        self.secret[:] = b"\x00" * len(self.secret)


def read_child_init(record: bytearray, expected_instance_id: str) -> NativeRuntimeIdentity:
    if len(record) > INIT_MAX_BYTES or not record.endswith(b"\n"):
        raise ValueError("registro de inicialização inválido")
    payload = bytes(record[:-1])
    if not payload.startswith(INIT_PREFIX):
        raise ValueError("registro de inicialização inválido")
    fields = payload[len(INIT_PREFIX) :].split(b"\t")
    if len(fields) != 4:
        raise ValueError("registro de inicialização inválido")
    instance_raw, secret_hex, dev_raw, ino_raw = fields
    if not re.fullmatch(rb"[A-Za-z0-9-]{1,128}", instance_raw):
        raise ValueError("registro de inicialização inválido")
    if instance_raw.decode("ascii", errors="strict") != expected_instance_id:
        raise ValueError("registro de inicialização inválido")
    if not re.fullmatch(rb"[0-9a-f]{64}", secret_hex):
        raise ValueError("registro de inicialização inválido")
    if not re.fullmatch(rb"(?:0|[1-9][0-9]*)", dev_raw) or not re.fullmatch(
        rb"(?:0|[1-9][0-9]*)", ino_raw
    ):
        raise ValueError("registro de inicialização inválido")
    try:
        directory_dev = int(dev_raw.decode("ascii"), 10)
        directory_ino = int(ino_raw.decode("ascii"), 10)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("registro de inicialização inválido") from exc
    current = Path(".").stat()
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (directory_dev, directory_ino):
        raise ValueError("diretório da geração mudou")
    identity = NativeRuntimeIdentity(
        instance_id=expected_instance_id,
        secret=bytearray.fromhex(secret_hex.decode("ascii")),
        directory_dev=directory_dev,
        directory_ino=directory_ino,
    )
    record[:] = b"\x00" * len(record)
    return identity


def proof_message(instance_id: str, nonce_hex: str) -> bytes:
    operation_result = f"pong:{instance_id}"
    return (
        "jarvis-local-transport-proof-v1\n"
        f"{PROTOCOL_VERSION}\n{RUNTIME_KIND}\n{instance_id}\n{BUILD_ID}\n"
        f"{nonce_hex}\n{operation_result}"
    ).encode("ascii")


def _proof_body(identity: NativeRuntimeIdentity, nonce_hex: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", nonce_hex):
        raise HTTPException(status_code=400, detail="requisição inválida")
    proof = hmac.new(identity.secret, proof_message(identity.instance_id, nonce_hex), hashlib.sha256).hexdigest()
    return (
        f"protocol_version={PROTOCOL_VERSION}\n"
        f"runtime_kind={RUNTIME_KIND}\n"
        f"instance_id={identity.instance_id}\n"
        f"build={BUILD_ID}\n"
        f"operation_result=pong:{identity.instance_id}\n"
        f"proof={proof}\n"
    ).encode("ascii")


def create_native_runtime_router(identity: NativeRuntimeIdentity) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok\n", media_type="text/plain")

    @router.get("/v1/version")
    def version() -> PlainTextResponse:
        body = (
            f"protocol_version={PROTOCOL_VERSION}\n"
            f"runtime_kind={RUNTIME_KIND}\n"
            f"instance_id={identity.instance_id}\n"
            f"build={BUILD_ID}\n"
        )
        return PlainTextResponse(body, media_type="text/plain")

    @router.post("/v1/instance-proof")
    async def instance_proof(request: Request) -> PlainTextResponse:
        try:
            nonce = (await request.body()).decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="requisição inválida") from exc
        return PlainTextResponse(_proof_body(identity, nonce), media_type="text/plain")

    return router


class NativeProtocolBoundary:
    """Closed HTTP/1.1 route and body boundary for the UDS-only app."""

    def __init__(self, app, identity: NativeRuntimeIdentity):
        self.app = app
        self.identity = identity

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        key = (method, path)
        if scope.get("http_version") != "1.1" or scope.get("query_string"):
            await self._reject(send, 400, b"request_rejected\n")
            return
        if key not in CONTROL_PATHS and key not in APP_PATHS:
            await self._reject(send, 404, b"route_rejected\n")
            return

        headers: dict[bytes, list[bytes]] = {}
        header_bytes = 0
        for name, value in scope.get("headers", []):
            headers.setdefault(name.lower(), []).append(value)
            header_bytes += len(name) + len(value) + 4
        if header_bytes > MAX_REQUEST_HEADER_BYTES:
            await self._reject(send, 431, b"headers_too_large\n")
            return
        if any(len(values) != 1 for values in headers.values()):
            await self._reject(send, 400, b"header_rejected\n")
            return
        if any(name not in ALLOWED_HEADERS for name in headers):
            await self._reject(send, 400, b"header_rejected\n")
            return
        host = headers.get(b"host", [b""])[0]
        content_type = headers.get(b"content-type", [b""])[0].lower()
        content_length_raw = headers.get(b"content-length", [b""])[0]
        connection = headers.get(b"connection", [b""])[0].lower()
        if (
            host != b"jarvis.local"
            or content_type not in {b"text/plain", b"text/plain; charset=utf-8"}
            or connection != b"close"
        ):
            await self._reject(send, 400, b"header_rejected\n")
            return
        try:
            content_length_text = content_length_raw.decode("ascii")
        except UnicodeDecodeError:
            await self._reject(send, 400, b"length_rejected\n")
            return
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)", content_length_text):
            await self._reject(send, 400, b"length_rejected\n")
            return
        content_length = int(content_length_text, 10)
        body_limit = CONTROL_REQUEST_MAX_BYTES if key in CONTROL_PATHS else APP_REQUEST_MAX_BYTES
        if key[0] == "GET":
            body_limit = 0
        if content_length < 0 or content_length > body_limit:
            await self._reject(send, 413, b"body_too_large\n")
            return

        chunks = bytearray()
        more_body = True
        try:
            async with asyncio.timeout(REQUEST_BODY_TIMEOUT_SECONDS):
                while more_body:
                    message = await receive()
                    if message["type"] != "http.request":
                        await self._reject(send, 400, b"body_rejected\n")
                        return
                    chunks.extend(message.get("body", b""))
                    if len(chunks) > body_limit:
                        await self._reject(send, 413, b"body_too_large\n")
                        return
                    more_body = message.get("more_body", False)
        except TimeoutError:
            await self._reject(send, 408, b"request_timeout\n")
            return
        if len(chunks) != content_length:
            await self._reject(send, 400, b"length_rejected\n")
            return
        if not self.identity.acknowledged.is_set():
            await self._reject(send, 503, b"runtime_not_ready\n")
            return

        delivered = False

        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(chunks), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_body, send)
        chunks[:] = b"\x00" * len(chunks)

    @staticmethod
    async def _reject(send, status: int, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
