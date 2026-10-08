"""Counter partition regressions; generated material stays in memory."""
import secrets
import threading
import pytest
import native_runtime as n

def _keystream_blocks(ciphertext: bytes, plaintext: bytes) -> set[bytes]:
    blocks = set()
    offset = 0
    while offset < len(ciphertext):
        end = min(offset + 16, len(ciphertext))
        blocks.add(bytes(left ^ right for left, right in zip(ciphertext[offset:end], plaintext[offset:end])))
        offset = end
    return blocks


def _request_frame(body: bytes) -> bytes:
    path = b"/v1/app/session/open"
    return bytes([n.ENVELOPE_VERSION, 1]) + len(path).to_bytes(2, "big") + len(body).to_bytes(4, "big") + path + body


@pytest.mark.parametrize("direction", [b"request", b"response"])
def test_consecutive_multiblock_known_plaintext_probe(direction):
    identity = n.NativeRuntimeIdentity("ctr-regression", bytearray(secrets.token_bytes(32)), 1, 1)
    unknown, known = secrets.token_bytes(100), bytes(100)
    if direction == b"request":
        frames = (_request_frame(unknown), _request_frame(known))
        seal = lambda nonce, frame: n._seal_application_envelope(identity, direction, nonce, frame)
    else:
        frames = (
            bytes([n.ENVELOPE_VERSION, 0, 200]) + len(unknown).to_bytes(4, "big") + unknown,
            bytes([n.ENVELOPE_VERSION, 0, 200]) + len(known).to_bytes(4, "big") + known,
        )
        seal = lambda nonce, frame: n._seal_application_envelope(identity, direction, nonce, frame)
    nonces = ((1).to_bytes(8, "big") + bytes(8), (2).to_bytes(8, "big") + bytes(8))
    sealed = [seal(nonce, frame) for nonce, frame in zip(nonces, frames)]
    streams = [_keystream_blocks(envelope[16:-32], frame) for envelope, frame in zip(sealed, frames)]
    v3_shared = len(streams[0] & streams[1])
    encryption_key = n._derive_key(identity, b"encryption", direction)
    prefix = b"\x11" * 8
    old = [
        n._aes_ctr(encryption_key, prefix + sequence.to_bytes(8, "big"), bytes(100))
        for sequence in (1, 2)
    ]
    old_shared = len(_keystream_blocks(old[0], bytes(100)) & _keystream_blocks(old[1], bytes(100)))
    identity.clear()
    assert old_shared > 0
    assert v3_shared == 0

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
    reserved = n.NativeRuntimeIdentity("ctr-accept", bytearray(secrets.token_bytes(32)), 1, 1)
    max_nonce = ((1 << 64) - 1).to_bytes(8, "big") + bytes(8)
    assert n._accept_request_nonce(reserved, max_nonce)
    assert not n._accept_request_nonce(reserved, (1).to_bytes(8, "big") + bytes(8))
    assert not n._accept_request_nonce(reserved, bytes(16))
    identity.clear()
    reserved.clear()


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
    assert identity.last_request_sequence == 0
    assert ("POST", "/v2/secure") not in n.ALLOWED_ROUTES
    identity.clear()


def test_replay_does_not_call_cipher_and_invalid_hmac_does_not_consume_sequence(monkeypatch):
    identity = n.NativeRuntimeIdentity("ctr-replay", bytearray(secrets.token_bytes(32)), 1, 1)
    frame = _request_frame(b"k=v\n")
    nonce = (4).to_bytes(8, "big") + bytes(8)
    envelope = n._seal_application_envelope(identity, b"request", nonce, frame)
    calls = []
    real_ctr = n._aes_ctr
    monkeypatch.setattr(n, "_aes_ctr", lambda *args: calls.append(1) or real_ctr(*args))
    assert n._decode_application_request(identity, envelope)[1] == "/v1/app/session/open"
    assert calls == [1]
    calls.clear()
    with pytest.raises(n.ReplayError):
        n._decode_application_request(identity, envelope)
    assert calls == []
    assert identity.last_request_sequence == 4
    forged = bytearray(envelope)
    forged[-1] ^= 1
    before = identity.last_request_sequence
    with pytest.raises(ValueError):
        n._open_application_envelope(identity, b"request", bytes(forged))
    assert calls == []
    assert identity.last_request_sequence == before
    identity.clear()


def test_authenticated_frame_failure_consumes_sequence(monkeypatch):
    identity = n.NativeRuntimeIdentity("ctr-consume", bytearray(secrets.token_bytes(32)), 1, 1)
    nonce = (6).to_bytes(8, "big") + bytes(8)
    plaintext = bytes([2, 1]) + (1).to_bytes(2, "big") + (0).to_bytes(4, "big") + b"x"
    envelope = n._seal_application_envelope(identity, b"request", nonce, plaintext)
    calls = []
    real_ctr = n._aes_ctr
    monkeypatch.setattr(n, "_aes_ctr", lambda *args: calls.append(1) or real_ctr(*args))
    with pytest.raises(ValueError):
        n._decode_application_request(identity, envelope)
    assert identity.last_request_sequence == 6
    assert calls == [1]
    calls.clear()
    with pytest.raises(n.ReplayError):
        n._decode_application_request(identity, envelope)
    assert calls == []
    identity.clear()


def test_thirty_two_concurrent_requests_with_the_same_nonce_decrypt_once(monkeypatch):
    identity = n.NativeRuntimeIdentity("ctr-concurrent", bytearray(secrets.token_bytes(32)), 1, 1)
    frame = _request_frame(b"k=v\n")
    nonce = (9).to_bytes(8, "big") + bytes(8)
    envelope = n._seal_application_envelope(identity, b"request", nonce, frame)
    calls = []
    call_lock = threading.Lock()
    real_ctr = n._aes_ctr

    def spy(*args):
        with call_lock:
            calls.append(1)
        return real_ctr(*args)

    monkeypatch.setattr(n, "_aes_ctr", spy)
    barrier = threading.Barrier(32)
    results = []
    result_lock = threading.Lock()

    def worker():
        barrier.wait()
        try:
            n._decode_application_request(identity, envelope)
            outcome = "ok"
        except n.ReplayError:
            outcome = "replay"
        with result_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("ok") == 1
    assert results.count("replay") == 31
    assert calls == [1]
    assert identity.last_request_sequence == 9
    identity.clear()
