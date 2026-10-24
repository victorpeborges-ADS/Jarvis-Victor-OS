"""Opt-in, process-local storage fixtures for encrypted-store tests."""
from __future__ import annotations

import secrets

import pytest

from memory_store import SQLiteMemoryStore


@pytest.fixture
def synthetic_storage_key() -> bytes:
    """Return a fresh test-only key that remains in this test process."""
    return secrets.token_bytes(32)


@pytest.fixture
def wrong_storage_key() -> bytes:
    """Return a distinct ephemeral key for negative authentication checks."""
    return secrets.token_bytes(32)


@pytest.fixture
def encrypted_store_factory(synthetic_storage_key):
    """Construct stores with one ephemeral key scoped to the current test."""

    def create(path=None, *, migrations_dir=None):
        return SQLiteMemoryStore(
            path,
            migrations_dir=migrations_dir,
            storage_key=synthetic_storage_key,
        )

    create.storage_key = synthetic_storage_key
    return create
