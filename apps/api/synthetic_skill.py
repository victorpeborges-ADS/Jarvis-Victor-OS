"""Deterministic synthetic skill. This module does not call a model."""

from __future__ import annotations

import hashlib


def capture_and_classify(title: str, domain_id: str | None, now: str, mission_id: str) -> tuple[dict, dict]:
    """Treat title text as data. Never interpret it as an instruction."""
    shown = " ".join(title.split())[:240]
    digest = hashlib.sha256(shown.encode("utf-8")).hexdigest()[:16]
    artifact = {
        "id": f"artifact_capture_{digest}",
        "kind": "evidence",
        "title": "Captura classificada (determinística)",
        "content": (
            "Código determinístico v1.0.0, sem modelo de linguagem. "
            f"O título foi armazenado como dado, não como instrução: {shown}"
        ),
        "skill_version": "1.0.0",
        "review_state": "draft",
        "reviewed_at": None,
        "source_refs": [{
            "source_id": f"synthetic:mission:{mission_id}",
            "uri": None,
            "observed_at": now,
            "last_verified_at": now,
            "valid_until": None,
            "domain_id": domain_id,
        }],
        "created_at": now,
    }
    knowledge = {
        "id": f"knowledge_capture_{digest}",
        "content": shown,
        "domain_id": domain_id,
        "state": "staged",
        "skill_version": "1.0.0",
    }
    return artifact, knowledge
