"""Ensaio móvel. Não compila APK, não abre aparelho e não envia rede."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backup_recovery import (
    LegacyDeletionConfirmationRequired,
    create_backup,
    restore_backup,
)
from memory_categories import read_memory, record_memory
from memory_store import SQLiteMemoryStore
from mobile_sync import (
    APK_BUILD,
    DEVICE_TEST,
    MAC_OFF_EXECUTION,
    OpenSync,
    MobileError,
    build_apk,
    is_demo_identifier,
    issue_identity,
    mac_execution,
    product_memory,
    remote_note,
)

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
T0 = 1_761_136_800
PASSPHRASE = "sintetica-backup-local"


def _ledger(path: Path) -> tuple[OpenSync, object]:
    ledger = OpenSync(path)
    identity = issue_identity("ensaio-a", now=T0)
    ledger.enroll(identity)
    return ledger, identity


def _op(identity, **fields):
    base = {
        "transport": "in_process",
        "relay": "ausente",
        "domain_id": "dom_synthetic_a",
        "device_clock": 10,
        "revision": 1,
    }
    base.update(fields)
    return identity.signed(base)


def test_demo_identifier_is_not_a_device_identity(tmp_path):
    for presented in ("app.jarvis.mobile", "demo-1", "DEMO"):
        assert is_demo_identifier(presented) is True
        with pytest.raises(MobileError, match="não é identidade"):
            issue_identity(presented, now=T0)
    ledger, identity = _ledger(tmp_path / "sync" / "ensaio.sqlite3")
    secret = identity.private_bytes()
    applied = ledger.apply(identity, _op(
        identity,
        op_id="a" * 32,
        kind="upsert",
        item_id="b" * 32,
        body="nota local",
    ), T0)
    assert applied["status"] == "aplicado"
    assert applied["mac_ran"] is False
    assert identity.fingerprint != identity.presented_id
    assert secret not in ledger.path.read_bytes()
    stored = ledger.read_item("b" * 32)
    assert stored is not None
    assert stored["label"] == "somente neste aparelho"
    ledger.close()


def test_lost_expired_and_rotated_devices_cannot_sync(tmp_path):
    ledger, identity = _ledger(tmp_path / "sync" / "pares.sqlite3")
    pending = _op(identity, op_id="c" * 32, kind="upsert", item_id="d" * 32, body="antes")
    ledger.mark_lost(identity)
    with pytest.raises(MobileError, match="dispositivo recusado"):
        ledger.apply(identity, pending, T0)
    assert ledger.read_item("d" * 32) is None

    second = issue_identity("ensaio-b", now=T0)
    ledger.enroll(second)
    stale = _op(second, op_id="e" * 32, kind="upsert", item_id="f" * 32, body="expirado")
    with pytest.raises(MobileError, match="dispositivo recusado"):
        ledger.apply(second, stale, T0 + 3601)
    assert ledger.read_item("f" * 32) is None

    third = issue_identity("ensaio-c", now=T0)
    ledger.enroll(third)
    old = _op(third, op_id="1" * 32, kind="upsert", item_id="2" * 32, body="gira")
    fresh = ledger.rotate(third, now=T0)
    with pytest.raises(MobileError, match="dispositivo recusado"):
        ledger.apply(third, old, T0)
    kept = ledger.apply(fresh, _op(
        fresh, op_id="3" * 32, kind="upsert", item_id="4" * 32, body="nova chave",
    ), T0)
    assert kept["status"] == "aplicado"
    assert ledger.read_item("2" * 32) is None
    assert ledger.read_item("4" * 32)["body"] == "nova chave"
    ledger.close()


def test_sync_does_not_resurrect_an_open_database_delete(tmp_path, encrypted_store_factory):
    path = tmp_path / "daily" / "memory.sqlite3"
    store = encrypted_store_factory(path)
    store.initialize()
    fact = record_memory(
        store, "owner", "dom_synthetic_a", "confirmed_fact",
        "fato que sai", "owner_confirmation", "owner-note", NOW,
    )
    archive = create_backup(
        path,
        tmp_path / "backups",
        PASSPHRASE,
        storage_key=encrypted_store_factory.storage_key,
    )
    archive_bytes = archive.read_bytes()
    ledger, identity = _ledger(tmp_path / "sync" / "exclusao.sqlite3")
    deleted = ledger.note_open_delete(store, identity, _op(
        identity,
        op_id="5" * 32,
        kind="delete",
        item_id=fact["id"],
        revision=2,
    ), T0, "confirmed_fact")
    assert deleted["removed_from_open_database"] is True
    assert deleted["historical_backup_may_keep_text"] is True
    assert deleted["resurrected"] is False
    assert deleted["cost"] == "não medido"
    with pytest.raises(ValueError, match="memória recusada"):
        read_memory(store, "owner", "dom_synthetic_a", "confirmed_fact", fact["id"])
    replay = ledger.apply(identity, _op(
        identity,
        op_id="6" * 32,
        kind="upsert",
        item_id=fact["id"],
        body="fato que sai",
        revision=9,
        device_clock=10**12,
    ), T0)
    assert replay["resurrected"] is False
    assert replay["status"] == "apagado"
    assert ledger.read_item(fact["id"]) is None
    with pytest.raises(ValueError, match="memória recusada"):
        read_memory(store, "owner", "dom_synthetic_a", "confirmed_fact", fact["id"])
    assert archive.read_bytes() == archive_bytes
    with pytest.raises(LegacyDeletionConfirmationRequired):
        restore_backup(
            archive,
            tmp_path / "restores",
            PASSPHRASE,
            storage_key=encrypted_store_factory.storage_key,
        )
    assert archive.read_bytes() == archive_bytes
    restored = encrypted_store_factory(restore_backup(
        archive,
        tmp_path / "restores",
        PASSPHRASE,
        storage_key=encrypted_store_factory.storage_key,
        confirm_legacy_resurrection=True,
    ))
    restored.initialize()
    assert read_memory(
        restored, "owner", "dom_synthetic_a", "confirmed_fact", fact["id"],
    )["body"] == "fato que sai"
    ledger.close()
    again = OpenSync(tmp_path / "sync" / "exclusao.sqlite3")
    assert again.read_item(fact["id"]) is None
    again.close()


def test_replay_conflict_and_clock_do_not_duplicate_or_leave_the_domain(tmp_path):
    ledger, identity = _ledger(tmp_path / "sync" / "conflito.sqlite3")
    item = "7" * 32
    first = _op(
        identity, op_id="8" * 32, kind="upsert", item_id=item,
        body="texto um", revision=2,
    )
    assert ledger.apply(identity, first, T0)["status"] == "aplicado"
    assert ledger.apply(identity, first, T0)["status"] == "aplicado"
    conflict = ledger.apply(identity, _op(
        identity, op_id="9" * 32, kind="upsert", item_id=item,
        body="texto dois", revision=2, device_clock=10**9,
    ), T0)
    assert conflict["status"] == "conflito"
    assert ledger.read_item(item)["body"] == "texto um"
    ignored = ledger.apply(identity, _op(
        identity, op_id="a1" + "b" * 30, kind="upsert", item_id=item,
        body="texto velho", revision=1, device_clock=10**12,
    ), T0)
    assert ignored["status"] == "ignorado"
    assert ledger.read_item(item)["revision"] == 2
    with pytest.raises(MobileError, match="domínio recusado"):
        ledger.apply(identity, _op(
            identity, op_id="c1" + "d" * 30, kind="upsert", item_id=item,
            body="outro dominio", revision=4, domain_id="dom_synthetic_b",
        ), T0)
    with pytest.raises(MobileError, match="transporte não declarado"):
        ledger.apply(identity, _op(
            identity, op_id="e1" + "f" * 30, kind="upsert", item_id=item,
            body="rede", revision=4, transport="https", relay="firebase",
        ), T0)
    extra = _op(identity, op_id="ab" * 16, kind="upsert", item_id=item, body="texto um", revision=3)
    extra["extra"] = 1
    with pytest.raises(MobileError, match="operação recusada"):
        ledger.apply(identity, extra, T0)
    assert ledger.read_item(item)["body"] == "texto um"
    ledger.close()
    reopened = OpenSync(tmp_path / "sync" / "conflito.sqlite3")
    assert reopened.read_item(item)["body"] == "texto um"
    reopened.close()


def test_remote_channel_apk_and_mac_off_stay_unpromised(tmp_path):
    ledger, identity = _ledger(tmp_path / "sync" / "canal.sqlite3")
    for kind in ("forwarded", "contact", "voice"):
        with pytest.raises(MobileError, match="não autoriza"):
            remote_note(identity, kind=kind, scope=identity.scope, body="oi", now=T0)
    with pytest.raises(MobileError, match="escopo separado"):
        remote_note(identity, kind="message", scope="effect", body="oi", now=T0)
    note = remote_note(identity, kind="message", scope=identity.scope, body="oi", now=T0)
    assert note["authorizes_effect"] is False
    assert note["sent"] is False
    assert note["status"] == "BLOCKED"
    assert note["cost"] == "não medido"
    package = build_apk()
    assert package["status"] == APK_BUILD == "NOT TESTED"
    assert package["device"] == DEVICE_TEST == "NOT TESTED"
    assert package["path"] == ""
    stopped = mac_execution(available=False)
    assert stopped["promised"] is False
    assert stopped["runs"] is False
    assert stopped["mac_off"] == MAC_OFF_EXECUTION
    assert mac_execution(available=True)["promised"] is False
    with pytest.raises(MobileError, match="localStorage"):
        product_memory("localStorage")
    assert product_memory("sqlite-temporario") == "sqlite-temporario"
    with pytest.raises(MobileError, match="caminho recusado"):
        OpenSync(Path("/tmp/Library/Application Support/Jarvis/memory.sqlite3"))
    source = Path(__file__).with_name("mobile_sync.py").read_text(encoding="utf-8")
    for needle in ("subprocess", "socket", "urlopen", "adb", "gradle", "emulator", "record_memory"):
        assert needle not in source
    ledger.close()
