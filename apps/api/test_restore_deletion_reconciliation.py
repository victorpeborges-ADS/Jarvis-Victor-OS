"""Post-snapshot deletion reconciliation, only disposable encrypted databases."""
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace
import errno
import os
import sqlite3
import subprocess
import sys

import pytest
import backup_recovery as backup
import database_leases as leases
import restore_activation as activation
from memory_store import MemoryStoreError
from local_captures import create_capture, delete_capture, list_captures, search_captures, open_capture, update_capture
from memory_categories import record_memory, delete_memory, page_memory, read_memory
from memory_deletions import write_tombstone
from sealed_database import MAGIC, read_encrypted_snapshot
from grounded_read import GroundedRead
from test_restore_activation import FAULTS, PASSWORD

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)
DOMAIN = 'dom_synthetic_a'


def ledger(store):
    with store.transaction() as c:
        return {tuple(r) for r in c.execute('SELECT category, domain_id, record_id, deleted_revision, content_sha256, operation_id, deleted_at FROM memory_deletion_tombstones')}


@pytest.fixture
def case(tmp_path, encrypted_store_factory):
    store = encrypted_store_factory(tmp_path / 'active' / 'memory.sqlite3')
    store.initialize()
    older = create_capture(store, 'owner', 'anterior sintetico', NOW)
    delete_capture(store, 'owner', older['id'], expected_revision=1)
    item = create_capture(store, 'owner', 'canario posterior sintetico', NOW)
    archive = backup.create_backup(store.path, tmp_path / 'archives', PASSWORD, storage_key=encrypted_store_factory.storage_key)
    delete_capture(store, 'owner', item['id'], expected_revision=1)
    return SimpleNamespace(store=store, item=item, older=older, archive=archive,
                           key=encrypted_store_factory.storage_key, factory=encrypted_store_factory,
                           expected=ledger(store), root=tmp_path)


def plan(case):
    return activation.prepare_activation(case.archive, case.store.path, PASSWORD, storage_key=case.key)


def assert_absent(store, identifier):
    assert list_captures(store, 'owner') == []
    assert search_captures(store, 'owner', 'canario') == ([], 0)
    with pytest.raises(ValueError):
        open_capture(store, 'owner', identifier)
    # These reads are the source discovery path used by grounded answers.
    reader = GroundedRead(SimpleNamespace(_provider=SimpleNamespace(provider_id='synthetic')), store, (), lambda _: None)
    assert reader._search_sources(('canario',), NOW) == []
    with store.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM local_captures').fetchone()[0] == 0


def test_union_survives_activation_backup_and_second_restore(case):
    previous = case.store
    # Divergent synthetic ledgers: older decision exists only in the backup,
    # later decision exists only in the current DB. Neither may be discarded.
    with previous.transaction() as c:
        c.execute('DELETE FROM memory_deletion_tombstones WHERE record_id=?', (case.older['id'],))
    prepared = plan(case)
    rollback = activation.activate(prepared, prepared.confirmation, storage_key=case.key)
    assert rollback.read_bytes().startswith(MAGIC)
    # A pre-activation handle cannot expose cached or old-generation data.
    with pytest.raises(MemoryStoreError, match='geração'):
        list_captures(previous, 'owner')
    restored = case.factory(previous.path)
    restored.initialize()
    assert_absent(restored, case.item['id'])
    assert ledger(restored) == case.expected
    archive = backup.create_backup(restored.path, case.root / 'future-backups', PASSWORD, storage_key=case.key)
    isolated = backup.restore_backup(archive, case.root / 'future-restores', PASSWORD, storage_key=case.key)
    future = case.factory(isolated)
    future.initialize()
    assert_absent(future, case.item['id'])
    assert ledger(future) == case.expected
    for path in leases.names(restored.path)[3].rglob('*'):
        if path.is_file():
            raw = path.read_bytes()
            assert not raw.startswith(b'SQLite format 3\x00')
            assert b'canario posterior sintetico' not in raw


@pytest.mark.parametrize('category,kind', [('confirmed_fact','owner_confirmation'), ('external_evidence','synthetic_source'), ('inferred_proposal','assistant_inference')])
@pytest.mark.parametrize('domain', [DOMAIN, 'dom_synthetic_b'])
def test_reconciles_each_category_and_domain(case, category, kind, domain):
    item = record_memory(case.store, 'owner', domain, category, 'categoria sintetica', kind, 'synthetic-origin', NOW)
    archive = backup.create_backup(case.store.path, case.root / 'category-backups', PASSWORD, storage_key=case.key)
    delete_memory(case.store, 'owner', domain, category, item['id'], expected_revision=1)
    prepared = activation.prepare_activation(archive, case.store.path, PASSWORD, storage_key=case.key)
    activation.activate(prepared, prepared.confirmation, storage_key=case.key)
    restored = case.factory(case.store.path); restored.initialize()
    assert page_memory(restored, 'owner', domain, category, 0) is None
    with pytest.raises(ValueError):
        read_memory(restored, 'owner', domain, category, item['id'])
    assert any(r[2] == item['id'] for r in ledger(restored))


def test_legacy_without_any_ledger_requires_explicit_confirmation(tmp_path, encrypted_store_factory):
    store = encrypted_store_factory(tmp_path / 'active' / 'memory.sqlite3'); store.initialize()
    create_capture(store, 'owner', 'legado sintetico', NOW)
    archive = backup.create_backup(store.path, tmp_path / 'archives', PASSWORD, storage_key=encrypted_store_factory.storage_key)
    before = store.path.read_bytes()
    with pytest.raises(backup.LegacyDeletionConfirmationRequired):
        activation.prepare_activation(archive, store.path, PASSWORD, storage_key=encrypted_store_factory.storage_key)
    assert store.path.read_bytes() == before
    assert not leases.names(store.path)[3].exists()
    prepared = activation.prepare_activation(archive, store.path, PASSWORD, storage_key=encrypted_store_factory.storage_key, confirm_legacy_resurrection=True)
    activation.activate(prepared, prepared.confirmation, storage_key=encrypted_store_factory.storage_key)
    restored = encrypted_store_factory(store.path); restored.initialize()
    assert list_captures(restored, 'owner')[0]['text'] == 'legado sintetico'


def test_stale_plan_after_concurrent_revision_or_deletion_fails_closed(case):
    prepared = plan(case)
    extra = create_capture(case.store, 'owner', 'nova revisao sintetica', NOW)
    update_capture(case.store, 'owner', extra['id'], 'revisao concorrente sintetica', expected_revision=1)
    delete_capture(case.store, 'owner', extra['id'], expected_revision=2)
    expected = ledger(case.store)
    before = case.store.path.read_bytes()
    with pytest.raises(activation.ActivationError, match='banco mudou'):
        activation.activate(prepared, prepared.confirmation, storage_key=case.key)
    assert case.store.path.read_bytes() == before
    assert ledger(case.store) == expected
    assert not leases.names(case.store.path)[3].exists()


@pytest.mark.parametrize('conflict', ['same-revision-content', 'different-deletion-revision', 'newer-row', 'invalid-operation'])
def test_conflicting_tombstone_or_revision_fails_before_staging(case, conflict):
    # Change only the synthetic current ledger. Archive retains the prior state.
    with case.store.transaction() as c:
        if conflict in ('same-revision-content', 'different-deletion-revision'):
            c.execute('DELETE FROM memory_deletion_tombstones WHERE record_id=?', (case.older['id'],))
            write_tombstone(c, category='explicit_capture', domain_id=DOMAIN, record_id=case.older['id'],
                            revision=2 if conflict == 'different-deletion-revision' else 1,
                            body='conteudo divergente sintetico', deleted_at=NOW)
        elif conflict == 'invalid-operation':
            c.execute("UPDATE memory_deletion_tombstones SET operation_id=? WHERE record_id=?", ('0'*64, case.item['id']))
        else:
            # Snapshot row revision 2 cannot be proven to supersede deletion 1.
            image = backup._open_archive(case.archive.read_bytes(), PASSWORD)
            with closing(sqlite3.connect(':memory:', isolation_level=None)) as src:
                src.deserialize(image)
                src.execute('UPDATE local_captures SET body=?, version=2 WHERE id=?', ('revisao divergente sintetica', case.item['id']))
                image = src.serialize()
            case.archive.write_bytes(backup._seal_snapshot(image, PASSWORD))
    expected = ledger(case.store)
    before = case.store.path.read_bytes()
    with pytest.raises(backup.BackupFormatError):
        plan(case)
    assert case.store.path.read_bytes() == before
    assert ledger(case.store) == expected
    assert not leases.names(case.store.path)[3].exists()


@pytest.mark.parametrize('which', [0, 1])
def test_replaced_lease_fails_before_switch(case, monkeypatch, which):
    prepared = plan(case)
    before = case.store.path.read_bytes()
    def replace_lease(point):
        if point == 'switch:before':
            path = leases.names(case.store.path)[which]
            replacement = path.with_suffix('.replacement')
            replacement.write_bytes(b''); replacement.chmod(0o600)
            os.replace(replacement, path)
    monkeypatch.setattr(activation, '_point', replace_lease)
    with pytest.raises(activation.ActivationError):
        activation.activate(prepared, prepared.confirmation, storage_key=case.key)
    assert case.store.path.read_bytes() == before
    monkeypatch.setattr(activation, '_point', lambda _: None)
    activation.recover_activation(case.store.path, storage_key=case.key)
    restored = case.factory(case.store.path); restored.initialize()
    assert ledger(restored) == case.expected
    assert_absent(restored, case.item['id'])


CHILD = '''
import os,sys
from pathlib import Path
import restore_activation as a
key=sys.stdin.buffer.read(32)
plan=a.prepare_activation(Path(sys.argv[1]),Path(sys.argv[2]),'synthetic-activation-password-only',storage_key=key)
def crash(point):
 if point == sys.argv[3]: os._exit(73)
a._point=crash
a.activate(plan,plan.confirmation,storage_key=key)
'''


@pytest.mark.parametrize('point', FAULTS)
def test_sealed_crash_every_activation_boundary_preserves_union(case, point):
    result = subprocess.run([sys.executable, '-c', CHILD, str(case.archive), str(case.store.path), point],
                            input=case.key, capture_output=True, cwd=Path(__file__).parent, timeout=30)
    assert result.returncode == 73, 'synthetic crash child failed; diagnostics withheld'
    root = leases.names(case.store.path)[3]
    if not (root / 'state.json').exists():
        with pytest.raises((OSError, backup.BackupError)):
            activation.recover_activation(case.store.path, storage_key=case.key)
        # No published intent means fail closed, but the old encrypted DB and
        # its complete ledger remain independently recoverable in memory.
        with closing(sqlite3.connect(':memory:')) as c:
            c.deserialize(read_encrypted_snapshot(case.store.path, case.key))
            assert {tuple(r) for r in c.execute('SELECT category, domain_id, record_id, deleted_revision, content_sha256, operation_id, deleted_at FROM memory_deletion_tombstones')} == case.expected
            assert c.execute('SELECT COUNT(*) FROM local_captures').fetchone()[0] == 0
    else:
        activation.recover_activation(case.store.path, storage_key=case.key)
        activation.recover_activation(case.store.path, storage_key=case.key)
        restored = case.factory(case.store.path); restored.initialize()
        assert ledger(restored) == case.expected
        assert_absent(restored, case.item['id'])
    for path in root.rglob('*'):
        if path.is_file():
            raw = path.read_bytes()
            assert not raw.startswith(b'SQLite format 3\x00')
            assert b'canario posterior sintetico' not in raw


@pytest.mark.parametrize('point', ['candidate:after_write', 'PREPARED:durable', 'switch:after', 'validation:after'])
@pytest.mark.parametrize('error', [errno.ENOSPC, errno.EIO, errno.EXDEV, errno.EACCES])
def test_sealed_io_failure_preserves_ledger_and_old_database(case, monkeypatch, point, error):
    prepared = plan(case)
    def fail(name):
        if name == point: raise OSError(error, 'synthetic fault')
    monkeypatch.setattr(activation, '_point', fail)
    with pytest.raises(activation.ActivationError):
        activation.activate(prepared, prepared.confirmation, storage_key=case.key)
    monkeypatch.setattr(activation, '_point', lambda _: None)
    activation.recover_activation(case.store.path, storage_key=case.key)
    restored = case.factory(case.store.path); restored.initialize()
    assert ledger(restored) == case.expected
    assert_absent(restored, case.item['id'])


def test_actual_preledger_backup_refuses_until_confirmed(tmp_path, encrypted_store_factory):
    from shutil import copyfile
    from memory_store import MIGRATIONS_DIR, SQLiteMemoryStore
    migrations = tmp_path / 'preledger-migrations'; migrations.mkdir(mode=0o700)
    for source in MIGRATIONS_DIR.glob('*.sql'):
        if source.name[:4].isdigit() and int(source.name[:4]) <= 25:
            copyfile(source, migrations / source.name)
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as c:
        from sealed_database import configure_memory_connection
        configure_memory_connection(c)
        SQLiteMemoryStore(tmp_path / 'validator-only', migrations_dir=migrations)._apply_migrations(c)
        c.execute("INSERT INTO local_captures(id, owner, domain_id, body, created_at) VALUES (?, 'owner', ?, 'legado anterior ao ledger', ?)", ('ab'*16, DOMAIN, NOW.isoformat()))
        image = c.serialize()
    archive = tmp_path / 'jarvis-backup-v1-synthetic-legacy.jvb'
    archive.write_bytes(backup._seal_snapshot(image, PASSWORD)); archive.chmod(0o600)
    original = archive.read_bytes()
    active = encrypted_store_factory(tmp_path / 'active' / 'memory.sqlite3'); active.initialize()
    key = encrypted_store_factory.storage_key
    before = active.path.read_bytes()
    with pytest.raises(backup.LegacyDeletionConfirmationRequired):
        activation.prepare_activation(archive, active.path, PASSWORD, storage_key=key)
    assert active.path.read_bytes() == before
    prepared = activation.prepare_activation(archive, active.path, PASSWORD, storage_key=key, confirm_legacy_resurrection=True)
    activation.activate(prepared, prepared.confirmation, storage_key=key)
    restored = encrypted_store_factory(active.path); restored.initialize()
    assert list_captures(restored, 'owner')[0]['id'] == 'ab'*16
    assert ledger(restored) == set()
    assert archive.read_bytes() == original


@pytest.mark.parametrize('point', ['rollback:before', 'rollback:after', 'rollback:durable', 'ROLLED_BACK:before_publish', 'ROLLED_BACK:after_publish', 'ROLLED_BACK:durable'])
def test_sealed_recovery_can_crash_without_losing_deletions(case, point):
    first = subprocess.run([sys.executable, '-c', CHILD, str(case.archive), str(case.store.path), 'switch:after'],
                           input=case.key, capture_output=True, cwd=Path(__file__).parent, timeout=30)
    assert first.returncode == 73, 'activation child failed; diagnostics withheld'
    child = '''
import sys,os
from pathlib import Path
import restore_activation as a
key=sys.stdin.buffer.read(32)
def crash(name):
 if name==sys.argv[2]: os._exit(74)
a._point=crash
a.recover_activation(Path(sys.argv[1]),storage_key=key)
'''
    result = subprocess.run([sys.executable, '-c', child, str(case.store.path), point], input=case.key,
                            capture_output=True, cwd=Path(__file__).parent, timeout=30)
    assert result.returncode == 74, 'recovery child failed; diagnostics withheld'
    # Both public initialization paths must recover before opening/migrating.
    restored = case.factory(case.store.path)
    restored.unlock(case.key)
    assert ledger(restored) == case.expected
    assert_absent(restored, case.item['id'])


def test_runtime_and_writer_leases_block_plan_and_activation(case):
    prepared = plan(case)
    for writer in (False, True):
        with leases.lock(case.store.path, writer=writer):
            with pytest.raises(leases.LeaseError):
                plan(case)
            with pytest.raises(leases.LeaseError):
                activation.activate(prepared, prepared.confirmation, storage_key=case.key)
    assert ledger(case.store) == case.expected


def test_backup_and_runtime_unlock_refuse_pending_activation(case, monkeypatch):
    prepared = plan(case)
    def fail(point):
        if point == 'switch:after': raise OSError('synthetic failure')
    monkeypatch.setattr(activation, '_point', fail)
    with pytest.raises(activation.ActivationError):
        activation.activate(prepared, prepared.confirmation, storage_key=case.key)
    with pytest.raises(activation.ActivationError, match='pendente'):
        backup.create_backup(case.store.path, case.root / 'blocked-backups', PASSWORD, storage_key=case.key)
    locked = case.factory(case.store.path)
    monkeypatch.setenv("JARVIS_DATABASE_PATH", str(case.store.path))
    with locked.runtime():
        with pytest.raises(activation.ActivationError, match='pendente'):
            locked.unlock(case.key)
        assert not locked.is_unlocked
    monkeypatch.setattr(activation, '_point', lambda _: None)
    locked.initialize() if locked.is_unlocked else locked.unlock(case.key)
    assert ledger(locked) == case.expected
