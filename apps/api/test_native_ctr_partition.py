"""Counter partition regressions; generated material stays in memory."""
import secrets
from types import SimpleNamespace
import pytest
import native_runtime as n
from test_native_app_api import AuthenticatedNativeTestClient

@pytest.mark.parametrize("direction", [b"request", b"response"])
def test_consecutive_multiblock_known_plaintext_probe(direction):
    identity = n.NativeRuntimeIdentity("ctr-regression", bytearray(secrets.token_bytes(32)), 1, 1)
    client = AuthenticatedNativeTestClient(SimpleNamespace(app=None), identity)
    unknown, known = secrets.token_bytes(96), bytes(96)
    path = b"/v1/app/session/open"
    a = client.seal_request(path.decode(), unknown)
    b = client.seal_request(path.decode(), known)
    if direction == b"request":
        frame = lambda body: bytes([n.ENVELOPE_VERSION, 1]) + len(path).to_bytes(2, "big") + len(body).to_bytes(4, "big") + path + body
    else:
        a = n._encode_application_response(identity, a[:16], 200, unknown)
        b = n._encode_application_response(identity, b[:16], 200, known)
        frame = lambda body: bytes([n.ENVELOPE_VERSION, 0, 200]) + len(body).to_bytes(4, "big") + body
    unknown_frame, known_frame = frame(unknown), frame(known)
    a, b = a[16:-32], b[16:-32]
    recovered = bytes(x ^ y ^ z for x, y, z in zip(a[16:], b, known_frame))
    failed = recovered == unknown_frame[16:]
    identity.clear()
    assert not failed, "consecutive messages reused CTR keystream"

@pytest.mark.parametrize("direction,limit", [(b"request", n.CTR_REQUEST_MAX_BYTES), (b"response", n.CTR_RESPONSE_MAX_BYTES)])
def test_counter_intervals_and_limits(direction, limit):
    identity = n.NativeRuntimeIdentity("ctr-limits", bytearray(secrets.token_bytes(32)), 1, 1)
    blocks = (limit + 15) // 16
    for sequence in (1, 2, (1 << 64) - 2, (1 << 64) - 1):
        nonce = sequence.to_bytes(8, "big") + bytes(8)
        start = int.from_bytes(nonce, "big")
        assert start + blocks - 1 < (sequence + 1) << 64
        envelope = n._seal_application_envelope(identity, direction, nonce, bytes(limit))
        _, opened = n._open_application_envelope(identity, direction, envelope)
        assert len(opened) == limit and not any(opened)
        with pytest.raises(ValueError):
            n._seal_application_envelope(identity, direction, nonce, bytes(limit + 1))
    for nonce in (bytes(16), bytes(8) + (1).to_bytes(8, "big"), (1).to_bytes(8, "big") + (1).to_bytes(8, "big")):
        with pytest.raises(ValueError):
            n._seal_application_envelope(identity, direction, nonce, bytes(32))
    max_nonce = ((1 << 64) - 1).to_bytes(8, "big") + bytes(8)
    assert n._accept_request_nonce(identity, max_nonce)
    assert not n._accept_request_nonce(identity, (1).to_bytes(8, "big") + bytes(8))
    assert not n._accept_request_nonce(identity, bytes(16))
    identity.clear()


def test_ctr_increments_big_endian_low_block_counter():
    key = secrets.token_bytes(32)
    nonce = (7).to_bytes(8, "big") + bytes(8)
    stream = n._aes_ctr(key, nonce, bytes(16 * 129))
    for block in (0, 1, 77, 128):
        independent = n._aes_ctr(key, (7).to_bytes(8, "big") + block.to_bytes(8, "big"), bytes(16))
        assert stream[block * 16:(block + 1) * 16] == independent


@pytest.mark.parametrize("direction", [b"request", b"response"])
def test_tamper_never_decrypts_and_old_protocol_fails_closed(direction, monkeypatch):
    identity = n.NativeRuntimeIdentity("ctr-tamper", bytearray(secrets.token_bytes(32)), 1, 1)
    nonce = (1).to_bytes(8, "big") + bytes(8)
    envelope = n._seal_application_envelope(identity, direction, nonce, secrets.token_bytes(96))
    calls = []
    monkeypatch.setattr(n, "_aes_ctr", lambda *args: calls.append(1))
    for position in (0, 16, len(envelope) - 1):
        changed = bytearray(envelope)
        changed[position] ^= 1
        with pytest.raises(ValueError):
            n._open_application_envelope(identity, direction, bytes(changed))
    for bad_nonce, ciphertext in (
        (nonce[:8] + (1).to_bytes(8, "big"), bytes(96)),
        (nonce, bytes((n.CTR_REQUEST_MAX_BYTES if direction == b"request" else n.CTR_RESPONSE_MAX_BYTES) + 1)),
    ):
        key = n._derive_key(identity, b"authentication", direction)
        tag = n.hmac.new(key, n._mac_message(identity, direction, bad_nonce, ciphertext), n.hashlib.sha256).digest()
        with pytest.raises(ValueError):
            n._open_application_envelope(identity, direction, bad_nonce + ciphertext + tag)
    assert not calls
    assert ("POST", "/v2/secure") not in n.ALLOWED_ROUTES
    identity.clear()
