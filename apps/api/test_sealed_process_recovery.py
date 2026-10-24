"""Process-boundary storage recovery; synthetic keys travel only in anonymous pipes."""
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

from sealed_database import MAGIC


CHILD = r'''
import sys
from pathlib import Path
from datetime import datetime, timezone
from memory_store import SQLiteMemoryStore, MemoryStoreError
from sealed_database import SealedDatabaseError
from local_captures import create_capture, list_captures
path, mode = Path(sys.argv[1]), sys.argv[2]
key = sys.stdin.buffer.read(32)
store = SQLiteMemoryStore(path)
if mode in ('missing', 'wrong'):
    try:
        if mode == 'missing':
            store.initialize()
        else:
            store.unlock(key)
    except (MemoryStoreError, SealedDatabaseError):
        assert not store.is_unlocked
        print('REFUSED', flush=True)
    else:
        raise AssertionError('invalid key accepted')
else:
    store.unlock(key)
    if mode == 'write':
        create_capture(store, 'owner', 'SYNTHETIC_PIPE_CRASH_CANARY', datetime.now(timezone.utc))
        print('COMMITTED', flush=True)
        sys.stdin.buffer.read(1)  # controller kills this process before any cleanup
        raise AssertionError('writer must receive SIGKILL')
    assert list_captures(store, 'owner')[0]['text'] == 'SYNTHETIC_PIPE_CRASH_CANARY'
    print('RECOVERED', flush=True)
    store.lock()
'''


def test_sigkill_then_distinct_process_reopens_with_pipe_key(tmp_path):
    import select
    database = tmp_path / 'private' / 'memory.sqlite3'
    key = secrets.token_bytes(32)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
           'PYTHONPATH': str(Path(__file__).parent),
           'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
           'TMPDIR': str(tmp_path)}

    def launch(mode):
        return subprocess.Popen([sys.executable, '-c', CHILD, str(database), mode],
                                cwd=tmp_path, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    writer = launch('write')
    try:
        writer.stdin.write(key)
        writer.stdin.flush()
        assert select.select([writer.stdout], [], [], 30)[0], 'writer did not commit'
        assert writer.stdout.readline() == b'COMMITTED\n'
        before = database.read_bytes()
        assert before.startswith(MAGIC)
        assert b'SYNTHETIC_PIPE_CRASH_CANARY' not in before
        writer.kill()
        assert writer.wait(timeout=10) == -signal.SIGKILL
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.wait(timeout=10)
        writer.stdin.close()
        writer.stdout.close()
        writer.stderr.close()

    for mode, supplied, expected in [('missing', b'', b'REFUSED\n'),
                                     ('wrong', secrets.token_bytes(32), b'REFUSED\n'),
                                     ('read', key, b'RECOVERED\n')]:
        child = launch(mode)
        try:
            stdout, stderr = child.communicate(supplied, timeout=30)
            assert child.returncode == 0, 'child failed (diagnostics withheld)'
            assert stdout == expected
            assert not stderr
            if mode in ('missing', 'wrong'):
                assert database.read_bytes() == before
            else:
                # A valid reopen can publish a freshly authenticated snapshot
                # with a new random nonce; the record is checked in the child.
                assert database.read_bytes().startswith(MAGIC)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)

    for path in tmp_path.rglob('*'):
        if path.is_file():
            raw = path.read_bytes()
            assert not raw.startswith(b'SQLite format 3\x00'), path.name
            assert b'SYNTHETIC_PIPE_CRASH_CANARY' not in raw, path.name
            assert not path.name.endswith(('-wal', '-shm', '-journal', '.pending', '.tmp')), path.name
