"""Connection helpers for tests of the encrypted API store."""

from __future__ import annotations

import sqlite3
import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def sqlite_rows(store, *, row_factory=None) -> Iterator[sqlite3.Connection]:
    """Open the store's in-memory SQLite view and close it after the test."""
    connection = store._connect()
    connection.row_factory = row_factory
    try:
        yield connection
    finally:
        connection.close()


def start_loopback_test_server(app, port: int, *, environment: dict[str, str | None] | None = None):
    """Start a same-process loopback server for concurrency tests.

    Tests inject their synthetic storage key into the app before calling this
    helper. The key never crosses a process boundary or enters the environment.
    """
    import uvicorn

    previous = {}
    for name, value in (environment or {}).items():
        previous[name] = os.environ.get(name)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="critical",
        server_header=False,
        date_header=False,
    ))
    thread = threading.Thread(target=server.run, name=f"api-test-{port}", daemon=True)
    server._test_thread = thread
    server._test_previous_environment = previous
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if server.started:
            return server
        if not thread.is_alive():
            stop_loopback_test_server(server)
            raise AssertionError("servidor API de teste encerrou antes de iniciar")
        time.sleep(0.025)
    stop_loopback_test_server(server)
    raise AssertionError("servidor API de teste não iniciou")


def stop_loopback_test_server(server) -> None:
    """Stop the local server, zero its test key, and restore process env."""
    server.should_exit = True
    thread = server._test_thread
    thread.join(timeout=10)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=2)
    app = getattr(server.config, "loaded_app", None)
    store = getattr(getattr(app, "state", None), "memory_store", None)
    if store is not None:
        store.lock()
    for name, value in server._test_previous_environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
