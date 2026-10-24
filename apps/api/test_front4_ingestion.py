"""Frente 4: ingestão aprovada, documento com origem e proposta revisada."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from approved_ingestion import IngestJob, hybrid_search_decision
from document_pages import origin_matches, render
from learned_proposals import note_regression, proposal_state, propose, publish, reject
from memory_store import SQLiteMemoryStore
import skill_registry


def _store(path: Path, encrypted_store_factory) -> SQLiteMemoryStore:
    store = encrypted_store_factory(path)
    store.initialize()
    return store


def _job(tmp_path: Path, encrypted_store_factory, name: str = "raiz") -> tuple[SQLiteMemoryStore, Path, IngestJob]:
    root = tmp_path / name
    root.mkdir()
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    return store, root, IngestJob(store, root, "dom_synthetic_a", "raiz-a")


def test_ignore_size_symlink_and_malformed_stay_out_of_the_index(tmp_path, encrypted_store_factory):
    _store_obj, root, job = _job(tmp_path, encrypted_store_factory)
    (root / ".jarvisignore").write_text("secreto.txt\n", encoding="utf-8")
    (root / "secreto.txt").write_text("nao indexar", encoding="utf-8")
    (root / "grande.txt").write_bytes(b"a" * 4097)
    outside = tmp_path / "fora.txt"
    outside.write_text("SEGREDO_FORA_DA_RAIZ", encoding="utf-8")
    (root / "atalho.txt").symlink_to(outside)
    (root / "quebrado.txt").write_bytes(b"\xff\xfe")
    (root / "pacote.zip").write_bytes(b"PK\x03\x04")
    for name in ("secreto.txt", "grande.txt", "atalho.txt", "quebrado.txt", "pacote.zip"):
        assert job.submit(name) == "aceito"
        result = job.step()
        assert result["indexed"] is False
    assert job.excerpt("secreto.txt") is None
    assert job.excerpt("atalho.txt") is None
    with _store_obj.transaction() as connection:
        blob = " ".join(
            row[0] for row in connection.execute("SELECT excerpt FROM approved_files")
        )
    assert "SEGREDO_FORA_DA_RAIZ" not in blob
    assert "nao indexar" not in blob


def test_partial_markdown_declares_the_empty_section_and_changed_file_updates(tmp_path, encrypted_store_factory):
    _store_obj, root, job = _job(tmp_path, encrypted_store_factory)
    (root / "nota.md").write_text(
        "## Um\n\ntexto presente\n\n## Dois\n\n",
        encoding="utf-8",
    )
    assert job.submit("nota.md") == "aceito"
    indexed = job.step()
    assert indexed["indexed"] is True
    assert indexed["missing"] == "Dois"
    assert job.excerpt("nota.md") == "texto presente"
    first = job.fingerprint("nota.md")
    (root / "nota.md").write_text("## Um\n\ntexto corrigido\n", encoding="utf-8")
    assert job.submit("nota.md") == "aceito"
    assert job.step()["indexed"] is True
    assert job.excerpt("nota.md") == "texto corrigido"
    assert job.fingerprint("nota.md") != first


def test_revoked_root_does_not_reindex_new_text(tmp_path, encrypted_store_factory):
    _store_obj, root, job = _job(tmp_path, encrypted_store_factory)
    (root / "nota.txt").write_text("texto antigo", encoding="utf-8")
    assert job.submit("nota.txt") == "aceito"
    assert job.step()["indexed"] is True
    kept = job.fingerprint("nota.txt")
    job.revoke()
    (root / "nota.txt").write_text("texto novo depois da revogacao", encoding="utf-8")
    assert job.submit("nota.txt") == "revogada"
    assert job.step() == {"status": "revogada", "indexed": False, "missing": ""}
    assert job.excerpt("nota.txt") == "texto antigo"
    assert job.fingerprint("nota.txt") == kept


def test_pause_resume_cancel_and_queue_limit(tmp_path, encrypted_store_factory):
    _store_obj, root, job = _job(tmp_path, encrypted_store_factory)
    (root / "um.txt").write_text("um", encoding="utf-8")
    assert job.submit("um.txt") == "aceito"
    job.pause()
    assert job.step()["status"] == "pausa"
    assert job.excerpt("um.txt") is None
    job.resume()
    assert job.step()["indexed"] is True
    job.cancel()
    (root / "dois.txt").write_text("dois", encoding="utf-8")
    assert job.submit("dois.txt") == "aceito"
    assert job.step()["status"] == "cancelado"
    assert job.excerpt("dois.txt") is None
    other = IngestJob(_store_obj, root, "dom_synthetic_a", "raiz-b")
    for index in range(4):
        assert other.submit(f"fila-{index}.txt") == "aceito"
    assert other.submit("fila-4.txt") == "fila_cheia"


def test_hybrid_search_is_not_adopted_and_creates_no_new_text_index(tmp_path, encrypted_store_factory):
    decision = hybrid_search_decision()
    assert decision == {"adopted": False, "reason": "sem_ganho_medido", "index": "literal"}
    store, _root, _ingest = _job(tmp_path, encrypted_store_factory)
    with store.transaction() as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )]
    assert not any("fts" in name.lower() for name in names)


def test_page_number_points_at_the_origin_and_office_formats_are_refused():
    pages = ((1, "src_nota", "dado sintetico"),)
    markdown = render("markdown", pages)
    html = render("html", pages)
    pdf = render("pdf", pages)
    assert origin_matches("markdown", markdown, pages)
    assert origin_matches("html", html, pages)
    assert origin_matches("pdf", pdf, pages)
    assert "<script" not in html.lower()
    assert b"pagina 1 origem src_nota" in pdf
    for kind in ("docx", "xlsx", "pptx"):
        with pytest.raises(ValueError, match="documento recusado"):
            render(kind, pages)


def test_skill_manifest_with_a_script_is_not_executed(tmp_path):
    root = tmp_path / "approved"
    state = tmp_path / "state"
    root.mkdir()
    state.mkdir()
    registry = skill_registry.SkillRegistry(root, state)
    path = root / "skill.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "id": "imported-reader",
        "version": "0.1.0",
        "origin": {"kind": "imported", "ref": "untrusted"},
        "license": {"name": "UNKNOWN", "spdx": None},
        "purpose": "Manifesto importado para leitura sintetica.",
        "capabilities": ["read_synthetic"],
        "inputs": {"type": "object", "additionalProperties": False},
        "outputs": {"type": "object", "additionalProperties": False},
        "side_effects": ["none"],
        "privacy": "synthetic_only",
        "script": "print(1)",
    }), encoding="utf-8")
    result = registry.import_manifest(path)
    assert result.ok is False
    assert result.record is not None
    assert result.record["executable"] is False
    assert "campo_executavel_recusado" in result.record["reasons"]
    assert "subprocess" not in Path(__file__).with_name("approved_ingestion.py").read_text(encoding="utf-8")


def test_rejection_persists_and_regression_blocks_publication(tmp_path, encrypted_store_factory):
    store = _store(tmp_path / "private" / "memory.sqlite3", encrypted_store_factory)
    rejected = propose(store, "dom_synthetic_a", "skill", "evidencia sintetica")
    reject(store, "dom_synthetic_a", rejected)
    with pytest.raises(ValueError, match="proposta recusada"):
        publish(store, "dom_synthetic_a", rejected)
    assert proposal_state(store, "dom_synthetic_a", rejected)[0] == "rejected"
    blocked = propose(store, "dom_synthetic_a", "memory", "outra evidencia")
    note_regression(store, "dom_synthetic_a", blocked)
    with pytest.raises(ValueError, match="proposta recusada"):
        publish(store, "dom_synthetic_a", blocked)
    assert proposal_state(store, "dom_synthetic_a", blocked)[2] == 0
    ready = propose(store, "dom_synthetic_a", "memory", "evidencia aceita")
    publish(store, "dom_synthetic_a", ready)
    assert proposal_state(store, "dom_synthetic_a", ready)[2] == 1
