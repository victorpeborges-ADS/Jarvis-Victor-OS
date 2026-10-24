"""Crash-safe rotation of a disposable synthetic sealed database."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backup_recovery import BACKUP_MAGIC, create_backup, restore_backup
from database_leases import LeaseError
from local_captures import create_capture, delete_capture, list_captures
from memory_categories import list_memory, record_memory
from main import create_native_app
from memory_store import SQLiteMemoryStore
from native_runtime import APP_PATHS, NativeRuntimeIdentity
from sealed_database import MAGIC, SQLITE_HEADER, KeychainUnavailable, PlaintextDatabaseRefused, inspect_pending_snapshots, open_snapshot
from storage_key_rotation import (
    CRASH_POINTS,
    DuplicateKeychainItem,
    RotationAmbiguous,
    RotationBlocked,
    RotationCrash,
    journal_path,
    finalize_rotation,
    mark_rotation_retired,
    operation_for,
    rotate_generation,
    select_account,
    _schema_fingerprint,
)
from test_native_app_api import HEADERS, AuthenticatedNativeTestClient, body, fields

CANARY = "CANARIO_ROTACAO_SINTETICO_7f14"
PASSWORD = "senha-sintetica-backup-2026"
PASSPHRASE = "senha-sintetica-mac003"


class MemoryKeychain:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.items: dict[str, bytes] = {}
        self.unavailable = unavailable
        self.stores = 0
        self.deletes: list[str] = []
        self.fail_delete = False

    def load(self, account: str) -> bytes | None:
        if self.unavailable:
            raise KeychainUnavailable("indisponível")
        value = self.items.get(account)
        return None if value is None else bytes(value)

    def store_new(self, account: str, key: bytes) -> None:
        if self.unavailable:
            raise KeychainUnavailable("indisponível")
        if account in self.items:
            raise DuplicateKeychainItem("duplicado")
        self.items[account] = bytes(key)
        self.stores += 1

    def delete(self, account: str) -> None:
        if self.unavailable or self.fail_delete:
            raise KeychainUnavailable("indisponível")
        self.deletes.append(account)
        self.items.pop(account, None)


def _same(left: bytes | None, right: bytes | None) -> bool:
    return left is not None and right is not None and hmac.compare_digest(left, right)


def _generation(database: Path | None = None) -> str:
    if database is None:
        return "gen-v1-" + secrets.token_hex(16)
    return "gen-v1-" + hashlib.sha256(database.read_bytes()).hexdigest()[:32]


def _sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, bytes, str]:
    database = tmp_path / "private" / "memory.sqlite3"
    monkeypatch.setenv("JARVIS_DATABASE_PATH", str(database))
    key = secrets.token_bytes(32)
    store = SQLiteMemoryStore(database)
    store.unlock(key)
    created = create_capture(store, "owner", CANARY, datetime.now(timezone.utc))
    store.lock()
    return database, key, created["id"]


def _keychain(key: bytes) -> MemoryKeychain:
    keychain = MemoryKeychain()
    keychain.items["primary"] = bytes(key)
    return keychain


def _assert_ciphertext(path: Path) -> None:
    blob = path.read_bytes()
    assert blob.startswith(MAGIC)
    assert not blob.startswith(SQLITE_HEADER)
    assert CANARY.encode() not in blob


def _assert_no_sqlite_plaintext(database: Path) -> None:
    for candidate in database.parent.iterdir():
        if candidate.is_file() and not candidate.name.endswith(".json"):
            head = candidate.read_bytes()[:16]
            assert not head.startswith(SQLITE_HEADER)
    for suffix in ("-wal", "-shm", "-journal"):
        assert not Path(f"{database}{suffix}").exists()


def _opens(blob: bytes, key: bytes) -> bool:
    try:
        image = open_snapshot(blob, key)
    except Exception:
        return False
    return CANARY.encode() in image


def _readable(database: Path, keychain: MemoryKeychain) -> bool:
    primary = database.read_bytes()
    for account, key in list(keychain.items.items()):
        if _opens(primary, key):
            return True
    for sibling in database.parent.glob(f".{database.name}.rotation-*.sealed"):
        blob = sibling.read_bytes()
        for key in list(keychain.items.values()):
            if _opens(blob, key):
                return True
    return False


def test_schema_fingerprint_rejects_an_empty_sqlite_image():
    connection = __import__("sqlite3").connect(":memory:")
    try:
        image = connection.serialize()
    finally:
        connection.close()
    with pytest.raises(Exception, match="schema incompatível"):
        _schema_fingerprint(image)


@pytest.mark.parametrize("point", CRASH_POINTS)
def test_each_crash_point_keeps_one_generation_and_resumes(tmp_path, monkeypatch, point):
    database, old_key, capture_id = _sealed(tmp_path, monkeypatch)
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)
    original = database.read_bytes()
    with pytest.raises(RotationCrash, match=point):
        rotate_generation(
            database,
            old_key=old_key,
            new_key=new_key,
            generation=generation,
            keychain=keychain,
            crash_after=point,
        )
    _assert_no_sqlite_plaintext(database)
    assert _readable(database, keychain)
    assert "primary" in keychain.items or _opens(database.read_bytes(), new_key)
    journal = journal_path(database).read_bytes()
    assert journal.startswith(b"JVRJT\x00\x01\x00")
    assert not journal.startswith(b"{")
    assert old_key not in journal and new_key not in journal
    assert old_key.hex().encode() not in journal and new_key.hex().encode() not in journal
    account = select_account(database, old_key, new_key)
    assert _opens(database.read_bytes(), keychain.load(account))
    result = rotate_generation(
        database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
    )
    assert result.phase == "finalized"
    assert result.cleanup == "complete"
    _assert_ciphertext(database)
    assert _opens(database.read_bytes(), new_key)
    assert not _opens(database.read_bytes(), old_key)
    assert keychain.load("primary") is None
    assert _same(keychain.load(generation), new_key)
    assert not list(database.parent.glob(f".{database.name}.rotation-*.sealed"))
    marker = database.parent / f".{database.name}.key-generation"
    assert marker.read_text(encoding="ascii").startswith(generation + "\n")
    again = rotate_generation(
        database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
    )
    assert again.phase == "finalized"
    assert again.key_changed is False
    assert keychain.stores == 1
    reopened = SQLiteMemoryStore(database)
    reopened.unlock(new_key)
    try:
        assert inspect_pending_snapshots(database, new_key) == ()
        assert any(item["id"] == capture_id for item in list_captures(reopened, "owner"))
        connection = reopened._connect()
        try:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
        finally:
            connection.close()
    finally:
        reopened.lock()
    if point == "intent":
        assert original == database.read_bytes() or _opens(database.read_bytes(), new_key)


def test_repeated_resume_after_the_same_crash_is_idempotent(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)
    for _attempt in range(2):
        with pytest.raises(RotationCrash):
            rotate_generation(
                database, old_key=old_key, new_key=new_key, generation=generation,
                keychain=keychain, crash_after="before_journal_published",
            )
        assert _opens(database.read_bytes(), new_key)
        assert _same(keychain.load("primary"), old_key)
    rotate_generation(
        database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
    )
    assert _opens(database.read_bytes(), new_key)
    assert keychain.load("primary") is None


def test_wrong_or_missing_old_key_does_not_publish_or_invent_a_key(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    original = hashlib.sha256(database.read_bytes()).hexdigest()
    generation = _generation(database)
    new_key = secrets.token_bytes(32)
    wrong = _keychain(old_key)
    with pytest.raises(RotationBlocked):
        rotate_generation(
            database, old_key=secrets.token_bytes(32), new_key=new_key,
            generation=generation, keychain=wrong,
        )
    assert not journal_path(database).exists()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == original
    assert wrong.stores == 0

    missing = MemoryKeychain()
    with pytest.raises(RotationBlocked, match="chave antiga ausente"):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation, keychain=missing,
        )
    assert missing.stores == 0
    assert not journal_path(database).exists()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == original


def test_unavailable_keychain_creates_neither_journal_nor_substitute(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    keychain = _keychain(old_key)
    keychain.unavailable = True
    with pytest.raises(KeychainUnavailable):
        rotate_generation(
            database, old_key=old_key, new_key=secrets.token_bytes(32),
            generation=_generation(), keychain=keychain,
        )
    assert keychain.stores == 0
    assert not journal_path(database).exists()


def test_missing_new_key_after_publish_does_not_invent_or_destroy(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)
    with pytest.raises(RotationCrash):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation,
            keychain=keychain, crash_after="published",
        )
    published = database.read_bytes()
    del keychain.items[generation]
    stores = keychain.stores
    with pytest.raises(RotationBlocked, match="chave nova ausente"):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
        )
    assert database.read_bytes() == published
    assert keychain.stores == stores
    assert generation not in keychain.items
    assert _same(keychain.load("primary"), old_key)
    assert list(database.parent.glob(f".{database.name}.rotation-*.sealed"))


def test_existing_generation_item_is_not_replaced(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    generation = _generation(database)
    keychain = _keychain(old_key)
    keychain.items[generation] = secrets.token_bytes(32)
    other = bytes(keychain.items[generation])
    with pytest.raises(DuplicateKeychainItem):
        rotate_generation(
            database, old_key=old_key, new_key=secrets.token_bytes(32),
            generation=generation, keychain=keychain,
        )
    assert _same(keychain.load(generation), other)
    assert _same(keychain.load("primary"), old_key)


def test_corrupt_journal_schema_and_sidecars_fail_closed(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    original = database.read_bytes()
    keychain = _keychain(old_key)
    journal_path(database).write_bytes(b'{"version":99}')
    os.chmod(journal_path(database), 0o600)
    with pytest.raises(RotationAmbiguous):
        rotate_generation(
            database, old_key=old_key, new_key=secrets.token_bytes(32),
            generation=_generation(), keychain=keychain,
        )
    assert journal_path(database).read_bytes() == b'{"version":99}'
    assert database.read_bytes() == original
    assert keychain.stores == 0 and keychain.deletes == []

    journal_path(database).unlink()
    wal = Path(f"{database}-wal")
    wal.write_bytes(b"residual")
    with pytest.raises(RotationBlocked, match="auxiliar"):
        rotate_generation(
            database, old_key=old_key, new_key=secrets.token_bytes(32),
            generation=_generation(), keychain=keychain,
        )
    assert wal.read_bytes() == b"residual"
    assert database.read_bytes() == original
    wal.unlink()

    database.write_bytes(SQLITE_HEADER + b"\x00" * 32)
    with pytest.raises(PlaintextDatabaseRefused):
        rotate_generation(
            database, old_key=old_key, new_key=secrets.token_bytes(32),
            generation=_generation(), keychain=keychain,
        )
    assert database.read_bytes().startswith(SQLITE_HEADER)


def test_published_validation_failure_restores_previous_ciphertext(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    original = hashlib.sha256(database.read_bytes()).hexdigest()
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)

    def reject(_image: bytes) -> None:
        from sealed_database import SealedDatabaseError
        raise SealedDatabaseError("schema incompatível")

    with pytest.raises(RotationBlocked, match="validação da geração nova falhou"):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
            published_validator=reject,
        )
    assert hashlib.sha256(database.read_bytes()).hexdigest() == original
    assert _opens(database.read_bytes(), old_key)
    assert _same(keychain.load("primary"), old_key)
    assert _same(keychain.load(generation), new_key)
    assert keychain.deletes == []
    recovery = list(database.parent.glob(f".{database.name}.rotation-*.sealed"))
    assert recovery and _opens(recovery[0].read_bytes(), old_key)
    _assert_no_sqlite_plaintext(database)
    rotate_generation(
        database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
    )
    assert _opens(database.read_bytes(), new_key)


def test_bad_recovery_file_is_not_deleted_or_applied(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)
    with pytest.raises(RotationCrash):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation,
            keychain=keychain, crash_after="linked",
        )
    original = database.read_bytes()
    recovery = next(database.parent.glob(f".{database.name}.rotation-*.sealed"))
    recovery.write_bytes(MAGIC + b"\x01" * 64)
    os.chmod(recovery, 0o600)
    with pytest.raises(RotationAmbiguous):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
        )
    assert database.read_bytes() == original
    assert recovery.read_bytes().startswith(MAGIC)
    assert _same(keychain.load("primary"), old_key)
    assert _same(keychain.load(generation), new_key)


def test_jvb_backup_is_not_a_rotation_and_stays_readable(tmp_path, monkeypatch):
    database, old_key, capture_id = _sealed(tmp_path, monkeypatch)
    archive = create_backup(database, tmp_path / "backups", PASSWORD, storage_key=old_key)
    archive_bytes = archive.read_bytes()
    assert archive_bytes.startswith(BACKUP_MAGIC)
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)
    rotate_generation(
        database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
    )
    assert archive.read_bytes() == archive_bytes
    disguised = tmp_path / "private" / "not-a-database.jvb"
    disguised.write_bytes(archive_bytes)
    os.chmod(disguised, 0o600)
    with pytest.raises(RotationBlocked):
        rotate_generation(
            disguised, old_key=old_key, new_key=secrets.token_bytes(32),
            generation=_generation(), keychain=keychain,
        )
    assert disguised.read_bytes() == archive_bytes
    restored = restore_backup(
        archive, tmp_path / "restores", PASSWORD, storage_key=new_key,
        confirm_legacy_resurrection=True,
    )
    assert restored.read_bytes().startswith(MAGIC)
    assert CANARY.encode() not in restored.read_bytes()
    reopened = SQLiteMemoryStore(database)
    reopened.unlock(new_key)
    try:
        assert any(item["id"] == capture_id for item in list_captures(reopened, "owner"))
    finally:
        reopened.lock()


def test_lease_conflict_does_not_start_rotation(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    original = database.read_bytes()
    keychain = _keychain(old_key)
    script = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "import database_leases as leases\n"
        "with leases.lock(Path(sys.argv[1]), exclusive=True):\n"
        "    sys.stdout.write('held\\n')\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(30)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(database)],
        cwd=Path(__file__).parent,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline() == "held\n"
        with pytest.raises(LeaseError):
            rotate_generation(
                database, old_key=old_key, new_key=secrets.token_bytes(32),
                generation=_generation(), keychain=keychain,
            )
    finally:
        process.kill()
        process.wait(timeout=5)
    assert database.read_bytes() == original
    assert not journal_path(database).exists()
    assert keychain.stores == 0


def test_runtime_route_rotates_then_locks_and_reopens(tmp_path, monkeypatch):
    database = tmp_path / "private" / "memory.sqlite3"
    monkeypatch.setenv("JARVIS_DATABASE_PATH", str(database))
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    from local_security import reset_state

    reset_state()
    identity = NativeRuntimeIdentity(
        instance_id="rotation-test",
        secret=bytearray(b"s" * 32),
        directory_dev=1,
        directory_ino=1,
    )
    identity.acknowledged.set()
    old_key = secrets.token_bytes(32)
    new_key = secrets.token_bytes(32)
    app = create_native_app(identity, database_path=database)
    with TestClient(app, base_url="http://jarvis.local", client=("127.0.0.1", 54021)) as client:
        client.headers.clear()
        authenticated = AuthenticatedNativeTestClient(client, identity)
        unlocked = authenticated.post(
            "/v1/app/storage/unlock",
            content=body(database_key=old_key.hex()),
            headers=HEADERS,
        )
        assert fields(unlocked)["state"] == "unlocked"
        created = create_capture(app.state.memory_store, "owner", CANARY, datetime.now(timezone.utc))
        generation = _generation(database)
        operation_id = hashlib.sha256(generation.encode("ascii")).hexdigest()
        rotated = authenticated.post(
            "/v1/app/storage/rotate",
            content=body(
                database_key=new_key.hex(), generation=generation,
                operation_id=operation_id, intent="begin",
            ),
            headers=HEADERS,
        )
        assert fields(rotated) == {
            "ok": "true", "state": "validated", "retire_account": "primary",
            "operation_id": operation_id, "cleanup": "pending",
        }
        extra = authenticated.post(
            "/v1/app/storage/rotate",
            content=body(
                database_key=new_key.hex(), generation=generation,
                operation_id=operation_id, intent="begin", extra="1",
            ),
            headers=HEADERS,
        )
        assert fields(extra) == {"ok": "false", "code": "storage_rotation_blocked"}
        retired = authenticated.post(
            "/v1/app/storage/rotate-retire",
            content=body(from_account="primary"),
            headers=HEADERS,
        )
        assert fields(retired) == {"ok": "true", "state": "committed"}
        assert list(database.parent.glob(f".{database.name}.rotation-*.sealed"))
        finalized = authenticated.post(
            "/v1/app/storage/rotate-finalize",
            content=body(database_key=new_key.hex(), operation_id=operation_id),
            headers=HEADERS,
        )
        assert fields(finalized) == {
            "ok": "true", "state": "finalized", "operation_id": operation_id, "cleanup": "complete",
        }
        assert not list(database.parent.glob(f".{database.name}.rotation-*.sealed"))
        assert ("POST", "/v1/app/storage/rotate") in APP_PATHS
        locked = authenticated.post("/v1/app/storage/lock", content=b"", headers=HEADERS)
        assert fields(locked)["state"] == "locked"
        refused = authenticated.post(
            "/v1/app/storage/unlock",
            content=body(database_key=old_key.hex()),
            headers=HEADERS,
        )
        assert fields(refused)["ok"] == "false"
        reopened = authenticated.post(
            "/v1/app/storage/unlock",
            content=body(database_key=new_key.hex()),
            headers=HEADERS,
        )
        assert fields(reopened)["state"] == "unlocked"
        assert any(item["id"] == created["id"] for item in list_captures(app.state.memory_store, "owner"))
    _assert_ciphertext(database)
    _assert_no_sqlite_plaintext(database)
    identity.clear()
    reset_state()


def test_mark_retired_without_validation_does_not_commit(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)
    with pytest.raises(RotationCrash):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation,
            keychain=keychain, crash_after="linked",
        )
    with pytest.raises(RotationBlocked):
        mark_rotation_retired(database, current_key=old_key, from_account="primary")
    assert _same(keychain.load("primary"), old_key)
    assert select_account(database, old_key, new_key) == "primary"


def test_failed_old_key_delete_keeps_recovery_and_blocks_another_generation(tmp_path, monkeypatch):
    database, old_key, _capture_id = _sealed(tmp_path, monkeypatch)
    new_key = secrets.token_bytes(32)
    generation = _generation(database)
    keychain = _keychain(old_key)
    with pytest.raises(RotationCrash):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation,
            keychain=keychain, crash_after="validated",
        )
    keychain.fail_delete = True
    with pytest.raises(KeychainUnavailable):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
        )
    assert _same(keychain.load("primary"), old_key)
    assert _same(keychain.load(generation), new_key)
    recovery = list(database.parent.glob(f".{database.name}.rotation-*.sealed"))
    assert recovery and _opens(recovery[0].read_bytes(), old_key)
    published = database.read_bytes()
    with pytest.raises(RotationBlocked, match="limpeza|pendente|andamento"):
        rotate_generation(
            database, old_key=new_key, new_key=secrets.token_bytes(32),
            generation=_generation(database), keychain=keychain, intent="begin",
        )
    assert database.read_bytes() == published
    assert recovery[0].exists()
    keychain.fail_delete = False
    with pytest.raises(RotationCrash):
        rotate_generation(
            database, old_key=old_key, new_key=new_key, generation=generation,
            keychain=keychain, crash_after="committed",
        )
    keychain.items["primary"] = bytes(old_key)
    with pytest.raises(RotationBlocked, match="chave antiga ainda presente"):
        finalize_rotation(
            database, current_key=new_key, operation_id=operation_for(generation), keychain=keychain,
        )
    assert recovery[0].exists() and database.read_bytes() == published
    del keychain.items["primary"]
    done = finalize_rotation(
        database, current_key=new_key, operation_id=operation_for(generation), keychain=keychain,
    )
    assert done.phase == "finalized"
    assert not recovery[0].exists()


def test_second_explicit_rotation_preserves_capture_fact_and_tombstone(tmp_path, monkeypatch):
    database, old_key, kept = _sealed(tmp_path, monkeypatch)
    store = SQLiteMemoryStore(database)
    store.unlock(old_key)
    now = datetime.now(timezone.utc)
    doomed = create_capture(store, "owner", "CAPTURA_REMOVIDA_7f14", now)
    tombstone = delete_capture(store, "owner", doomed["id"], 1)
    fact = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact", "fato sintetico",
        "owner_confirmation", "ref-sintetica", now,
    )
    store.lock()
    generation = _generation(database)
    new_key = secrets.token_bytes(32)
    keychain = _keychain(old_key)
    first = rotate_generation(
        database, old_key=old_key, new_key=new_key, generation=generation, keychain=keychain,
    )
    assert first.phase == "finalized" and first.key_changed is True
    sealed_after_first = hashlib.sha256(database.read_bytes()).hexdigest()
    repeated = rotate_generation(
        database, old_key=new_key, new_key=new_key, generation=generation,
        keychain=keychain, intent="resume",
    )
    assert repeated.key_changed is False
    assert hashlib.sha256(database.read_bytes()).hexdigest() == sealed_after_first
    assert keychain.stores == 1
    third_key = secrets.token_bytes(32)
    next_generation = _generation(database)
    with pytest.raises(RotationCrash):
        rotate_generation(
            database, old_key=new_key, new_key=third_key, generation=next_generation,
            keychain=keychain, intent="begin", crash_after="committed",
        )
    assert list(database.parent.glob(f".{database.name}.rotation-*.sealed"))
    during = database.read_bytes()
    old_retry = rotate_generation(
        database, old_key=third_key, new_key=third_key, generation=generation,
        keychain=keychain, intent="resume",
    )
    assert old_retry.phase == "finalized" and old_retry.key_changed is False
    assert database.read_bytes() == during
    done = rotate_generation(
        database, old_key=new_key, new_key=third_key, generation=next_generation,
        keychain=keychain, intent="begin",
    )
    assert done.phase == "finalized"
    assert done.to_account == next_generation
    assert not list(database.parent.glob(f".{database.name}.rotation-*.sealed"))
    final_bytes = database.read_bytes()
    stale = rotate_generation(
        database, old_key=third_key, new_key=third_key, generation=generation,
        keychain=keychain, intent="resume",
    )
    assert stale.key_changed is False and stale.operation_id == operation_for(generation)
    assert database.read_bytes() == final_bytes
    assert keychain.load(generation) is None
    assert _same(keychain.load(next_generation), third_key)
    journal = journal_path(database).read_bytes()
    assert journal.startswith(b"JVRJT\x00\x01\x00")
    assert third_key not in journal and old_key not in journal
    reopened = SQLiteMemoryStore(database)
    reopened.unlock(third_key)
    try:
        assert any(item["id"] == kept for item in list_captures(reopened, "owner"))
        assert any(item["id"] == fact["id"] for item in list_memory(
            reopened, "owner", "dom_synthetic_a", "confirmed_fact",
        ))
        connection = reopened._connect()
        try:
            row = connection.execute(
                "SELECT operation_id FROM memory_deletion_tombstones WHERE record_id = ?",
                (doomed["id"],),
            ).fetchone()
            assert row is not None and row[0] == tombstone["operation_id"]
            image = open_snapshot(database.read_bytes(), third_key)
            assert _schema_fingerprint(image)
        finally:
            connection.close()
    finally:
        reopened.lock()
    assert not _opens(final_bytes, old_key)
    assert not _opens(final_bytes, new_key)
    _assert_no_sqlite_plaintext(database)
    _assert_ciphertext(database)
