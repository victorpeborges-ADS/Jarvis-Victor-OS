"""Proposta de memória ou skill. Publicação exige evidência e revisão.

Rejeição permanece. Regressão impede publicar. Este módulo não executa script.
"""

from __future__ import annotations

import secrets

from memory_categories import DOMAINS
from memory_store import SQLiteMemoryStore


def propose(
    store: SQLiteMemoryStore,
    domain_id: str,
    kind: str,
    evidence: str,
) -> str:
    if domain_id not in DOMAINS or kind not in {"memory", "skill"}:
        raise ValueError("proposta recusada")
    if not isinstance(evidence, str) or not 1 <= len(evidence) <= 400:
        raise ValueError("proposta recusada")
    proposal_id = secrets.token_hex(16)
    with store.transaction() as connection:
        connection.execute(
            """INSERT INTO learned_proposals(
                   id, owner, domain_id, kind, evidence, status, regression, published
               ) VALUES (?, 'owner', ?, ?, ?, 'pending', 0, 0)""",
            (proposal_id, domain_id, kind, evidence),
        )
    return proposal_id


def reject(store: SQLiteMemoryStore, domain_id: str, proposal_id: str) -> None:
    _update_status(store, domain_id, proposal_id, "rejected")


def note_regression(store: SQLiteMemoryStore, domain_id: str, proposal_id: str) -> None:
    with store.transaction() as connection:
        updated = connection.execute(
            """UPDATE learned_proposals SET regression = 1
               WHERE id = ? AND owner = 'owner' AND domain_id = ? AND published = 0""",
            (proposal_id, domain_id),
        ).rowcount
    if updated != 1:
        raise ValueError("proposta recusada")


def publish(store: SQLiteMemoryStore, domain_id: str, proposal_id: str) -> None:
    with store.transaction() as connection:
        row = connection.execute(
            """SELECT status, regression, evidence FROM learned_proposals
               WHERE id = ? AND owner = 'owner' AND domain_id = ?""",
            (proposal_id, domain_id),
        ).fetchone()
        if row is None or row[0] != "pending" or row[1] != 0 or row[2] == "":
            raise ValueError("proposta recusada")
        connection.execute(
            """UPDATE learned_proposals SET published = 1
               WHERE id = ? AND owner = 'owner' AND domain_id = ? AND status = 'pending'""",
            (proposal_id, domain_id),
        )


def proposal_state(store: SQLiteMemoryStore, domain_id: str, proposal_id: str) -> tuple[str, int, int]:
    with store.transaction() as connection:
        row = connection.execute(
            """SELECT status, regression, published FROM learned_proposals
               WHERE id = ? AND owner = 'owner' AND domain_id = ?""",
            (proposal_id, domain_id),
        ).fetchone()
    if row is None:
        raise ValueError("proposta recusada")
    return row[0], row[1], row[2]


def _update_status(store: SQLiteMemoryStore, domain_id: str, proposal_id: str, status: str) -> None:
    with store.transaction() as connection:
        updated = connection.execute(
            """UPDATE learned_proposals SET status = ?
               WHERE id = ? AND owner = 'owner' AND domain_id = ? AND published = 0""",
            (status, proposal_id, domain_id),
        ).rowcount
    if updated != 1:
        raise ValueError("proposta recusada")
