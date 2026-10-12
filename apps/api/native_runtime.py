"""Private UDS routes and framing for the supervised FastAPI runtime."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

PROTOCOL_VERSION = "3"
RUNTIME_KIND = "jarvis-synthetic"
BUILD_ID = "g6-mac-002-2-encrypted-uds-v3"
INIT_PREFIX = b"JARVIS_TRANSPORT_INIT "
INIT_MAX_BYTES = 1024
APP_REQUEST_MAX_BYTES = 1024
APP_RESPONSE_MAX_BYTES = 2048
ENVELOPE_REQUEST_MAX_BYTES = APP_REQUEST_MAX_BYTES + 256
CONTROL_REQUEST_MAX_BYTES = 128
MAX_REQUEST_HEADER_BYTES = 1024
REQUEST_BODY_TIMEOUT_SECONDS = 0.9
ENVELOPE_VERSION = 3
ENVELOPE_NONCE_BYTES = 16
ENVELOPE_SEQUENCE_BYTES = 8
ENVELOPE_TAG_BYTES = 32
CTR_REQUEST_MAX_BYTES = ENVELOPE_REQUEST_MAX_BYTES - ENVELOPE_NONCE_BYTES - ENVELOPE_TAG_BYTES
CTR_RESPONSE_MAX_BYTES = APP_RESPONSE_MAX_BYTES + 7
ENVELOPE_ROUTE = "/v3/secure"
ENVELOPE_RESPONSE_MAX_BYTES = APP_RESPONSE_MAX_BYTES + ENVELOPE_NONCE_BYTES + ENVELOPE_TAG_BYTES + 7
APP_PATHS = frozenset(
    {
        ("POST", "/v1/app/session/open"),
        ("POST", "/v1/app/session/close"),
        ("POST", "/v1/app/grants/mission-read"),
        ("POST", "/v1/app/grants/mission-read/revoke"),
        ("POST", "/v1/app/missions/list"),
        ("POST", "/v1/app/captures/create"),
        ("POST", "/v1/app/captures/edit"),
        ("POST", "/v1/app/captures/delete"),
        ("POST", "/v1/app/captures/list"),
        ("POST", "/v1/app/captures/clear"),
        ("POST", "/v1/app/connectors/status"),
        ("POST", "/v1/app/grants/mission-review"),
        ("POST", "/v1/app/reviews/pending"),
        ("POST", "/v1/app/reviews/draft"),
        ("POST", "/v1/app/reviews/detail"),
        ("POST", "/v1/app/reviews/approve"),
    }
)
CONTROL_PATHS = frozenset(
    {
        ("GET", "/v1/health"),
        ("GET", "/v1/version"),
        ("POST", "/v1/instance-proof"),
    }
)
ALLOWED_ROUTES = CONTROL_PATHS | {("POST", ENVELOPE_ROUTE)}
ALLOWED_HEADERS = frozenset({b"host", b"content-type", b"content-length", b"connection"})


@dataclass
class NativeRuntimeIdentity:
    instance_id: str
    secret: bytearray = field(repr=False)
    directory_dev: int
    directory_ino: int
    acknowledged: Event = field(default_factory=Event, repr=False)
    replay_lock: Lock = field(default_factory=Lock, repr=False)
    last_request_sequence: int = field(default=0, repr=False)

    def clear(self) -> None:
        self.secret[:] = b"\x00" * len(self.secret)
        with self.replay_lock:
            self.last_request_sequence = 0


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
        "jarvis-local-transport-proof-v3\n"
        f"{PROTOCOL_VERSION}\n{RUNTIME_KIND}\n{instance_id}\n{BUILD_ID}\n"
        f"{nonce_hex}\n{operation_result}"
    ).encode("ascii")


def _key_context(purpose: bytes, direction: bytes, instance_id: str) -> bytes:
    return (
        b"jarvis-local-envelope-v3\x00"
        + purpose
        + b"\x00"
        + direction
        + b"\x00"
        + instance_id.encode("ascii")
    )


def _derive_key(identity: NativeRuntimeIdentity, purpose: bytes, direction: bytes) -> bytes:
    return hmac.new(
        identity.secret,
        _key_context(purpose, direction, identity.instance_id),
        hashlib.sha256,
    ).digest()


def _mac_message(identity: NativeRuntimeIdentity, direction: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    return (
        b"jarvis-local-envelope-v3\x00"
        + identity.instance_id.encode("ascii")
        + b"\x00"
        + direction
        + b"\x00"
        + ENVELOPE_ROUTE.encode("ascii")
        + b"\x00"
        + nonce
        + ciphertext
    )


def _validate_counter_partition(direction: bytes, nonce: bytes, size: int) -> None:
    limit = {b"request": CTR_REQUEST_MAX_BYTES, b"response": CTR_RESPONSE_MAX_BYTES}.get(direction)
    # Each sequence owns [sequence * 2**64, sequence * 2**64 + ceil(size/16) - 1].
    if (
        limit is None
        or size < 0
        or size > limit
        or len(nonce) != 16
        or int.from_bytes(nonce[:8], "big") == 0
        or nonce[8:] != bytes(8)
    ):
        raise ValueError("invalid counter partition")


def _aes_ctr(key: bytes, nonce: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce)).encryptor()
    return cipher.update(data) + cipher.finalize()


def _seal_application_envelope(
    identity: NativeRuntimeIdentity,
    direction: bytes,
    nonce: bytes,
    plaintext: bytes,
) -> bytes:
    """Serialize one authenticated, encrypted protocol-v3 message."""
    _validate_counter_partition(direction, nonce, len(plaintext))
    encryption_key = _derive_key(identity, b"encryption", direction)
    authentication_key = _derive_key(identity, b"authentication", direction)
    ciphertext = _aes_ctr(encryption_key, nonce, plaintext)
    tag = hmac.new(
        authentication_key,
        _mac_message(identity, direction, nonce, ciphertext),
        hashlib.sha256,
    ).digest()
    return nonce + ciphertext + tag


def _open_application_envelope(
    identity: NativeRuntimeIdentity,
    direction: bytes,
    envelope: bytes,
) -> tuple[bytes, bytes]:
    if len(envelope) < ENVELOPE_NONCE_BYTES + ENVELOPE_TAG_BYTES:
        raise ValueError("invalid envelope")
    nonce = envelope[:ENVELOPE_NONCE_BYTES]
    ciphertext = envelope[ENVELOPE_NONCE_BYTES:-ENVELOPE_TAG_BYTES]
    tag = envelope[-ENVELOPE_TAG_BYTES:]
    authentication_key = _derive_key(identity, b"authentication", direction)
    expected = hmac.new(
        authentication_key,
        _mac_message(identity, direction, nonce, ciphertext),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("invalid envelope")
    _validate_counter_partition(direction, nonce, len(ciphertext))
    if direction == b"request":
        # Canonical, authenticated requests consume the sequence before CTR.
        # A later framing or dispatch failure does not release it. HMAC failure,
        # a non-canonical nonce, and an oversized ciphertext never reach here.
        _reserve_request_sequence(identity, nonce)
    encryption_key = _derive_key(identity, b"encryption", direction)
    return nonce, _aes_ctr(encryption_key, nonce, ciphertext)


class ReplayError(ValueError):
    pass


def _reserve_request_sequence(identity: NativeRuntimeIdentity, nonce: bytes) -> None:
    sequence = int.from_bytes(nonce[:ENVELOPE_SEQUENCE_BYTES], "big")
    with identity.replay_lock:
        if sequence <= identity.last_request_sequence:
            raise ReplayError
        identity.last_request_sequence = sequence


def _accept_request_nonce(identity: NativeRuntimeIdentity, nonce: bytes) -> bool:
    if len(nonce) != ENVELOPE_NONCE_BYTES:
        return False
    sequence = int.from_bytes(nonce[:ENVELOPE_SEQUENCE_BYTES], "big")
    if sequence == 0 or nonce[ENVELOPE_SEQUENCE_BYTES:] != bytes(8):
        return False
    try:
        _reserve_request_sequence(identity, nonce)
    except ReplayError:
        return False
    return True


class RequestTooLargeError(ValueError):
    pass


def _decode_application_request(identity: NativeRuntimeIdentity, envelope: bytes):
    if len(envelope) < ENVELOPE_NONCE_BYTES + ENVELOPE_TAG_BYTES + 8:
        raise ValueError("invalid envelope")
    nonce, plaintext = _open_application_envelope(identity, b"request", envelope)
    if len(plaintext) < 8 or plaintext[0] != ENVELOPE_VERSION or plaintext[1] != 1:
        raise ValueError("invalid request frame")
    path_length = int.from_bytes(plaintext[2:4], "big")
    body_length = int.from_bytes(plaintext[4:8], "big")
    if path_length == 0 or len(plaintext) != 8 + path_length + body_length:
        raise ValueError("invalid request frame")
    if body_length > APP_REQUEST_MAX_BYTES:
        raise RequestTooLargeError
    try:
        path = plaintext[8 : 8 + path_length].decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid request frame") from exc
    if ("POST", path) not in APP_PATHS:
        raise ValueError("route rejected")
    return nonce, path, bytes(plaintext[8 + path_length :])


def _encode_application_response(identity: NativeRuntimeIdentity, nonce: bytes, status: int, body: bytes) -> bytes:
    if len(body) > APP_RESPONSE_MAX_BYTES:
        status = 500
        body = b"response_too_large\n"
    plaintext = (
        bytes([ENVELOPE_VERSION])
        + status.to_bytes(2, "big")
        + len(body).to_bytes(4, "big")
        + body
    )
    return _seal_application_envelope(identity, b"response", nonce, plaintext)


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
        if key not in ALLOWED_ROUTES:
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
        expected_content_type = (
            b"application/octet-stream" if key == ("POST", ENVELOPE_ROUTE) else b"text/plain"
        )
        if (
            host != b"jarvis.local"
            or content_type not in {expected_content_type, expected_content_type + b"; charset=utf-8"}
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
        body_limit = (
            CONTROL_REQUEST_MAX_BYTES
            if key in CONTROL_PATHS
            else ENVELOPE_REQUEST_MAX_BYTES
        )
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

        if key in CONTROL_PATHS:
            delivered = False

            async def replay_control_body():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(chunks), "more_body": False}
                return {"type": "http.disconnect"}

            await self.app(scope, replay_control_body, send)
            chunks[:] = b"\x00" * len(chunks)
            return

        try:
            nonce, inner_path, inner_body = _decode_application_request(self.identity, bytes(chunks))
        except ReplayError:
            chunks[:] = b"\x00" * len(chunks)
            await self._reject(send, 409, b"request_rejected\n")
            return
        except RequestTooLargeError:
            chunks[:] = b"\x00" * len(chunks)
            await self._reject(send, 413, b"body_too_large\n")
            return
        except (ValueError, UnicodeError):
            chunks[:] = b"\x00" * len(chunks)
            await self._reject(send, 401, b"request_rejected\n")
            return

        inner_scope = dict(scope)
        inner_scope["method"] = "POST"
        inner_scope["path"] = inner_path
        inner_scope["raw_path"] = inner_path.encode("ascii")
        inner_scope["query_string"] = b""
        inner_scope["headers"] = [
            (b"host", b"jarvis.local"),
            (b"content-type", b"text/plain"),
            (b"content-length", str(len(inner_body)).encode("ascii")),
            (b"connection", b"close"),
        ]
        delivered = False
        response_status: int | None = None
        response_body = bytearray()

        async def replay_application_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": inner_body, "more_body": False}
            return {"type": "http.disconnect"}

        async def capture_application_response(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message.get("status", 500))
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        try:
            await self.app(inner_scope, replay_application_body, capture_application_response)
            if response_status is None:
                response_status = 500
                response_body[:] = b"ok=false\ncode=operation_failed\n"
        except Exception:
            response_status = 500
            response_body[:] = b"ok=false\ncode=operation_failed\n"

        if len(response_body) > APP_RESPONSE_MAX_BYTES:
            response_status = 500
            response_body[:] = b"response_too_large\n"
        response_envelope = _encode_application_response(
            self.identity,
            nonce,
            response_status,
            bytes(response_body),
        )
        inner_body = b"\x00" * len(inner_body)
        response_body[:] = b"\x00" * len(response_body)
        chunks[:] = b"\x00" * len(chunks)
        await self._respond(send, 200, response_envelope, b"application/octet-stream")

    @staticmethod
    async def _reject(send, status: int, body: bytes) -> None:
        await NativeProtocolBoundary._respond(send, status, body, b"text/plain")

    @staticmethod
    async def _respond(send, status: int, body: bytes, content_type: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", content_type),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
