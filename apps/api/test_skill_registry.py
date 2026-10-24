import json
import os
from pathlib import Path

import pytest

import skill_registry

READ = skill_registry.Permission("read_synthetic", "synthetic", "local-test")
GENERATE = skill_registry.Permission("generate_synthetic_document", "synthetic", "local-test")
TOKEN = "NAO_EXECUTAR_7f3a"
SECRET = "SEGREDO_FORA_DA_RAIZ"


def open_registry(tmp_path: Path):
    root = tmp_path / "approved"
    state = tmp_path / "state"
    root.mkdir()
    state.mkdir()
    return skill_registry.SkillRegistry(root, state), root, state


def manifest_body(**overrides) -> dict:
    body = {
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
    }
    body.update(overrides)
    return body


def write_manifest(directory: Path, name: str = "skill.json", **overrides) -> Path:
    path = directory / name
    path.write_text(json.dumps(manifest_body(**overrides)), encoding="utf-8")
    return path


def state_text(state: Path) -> str:
    chunks = []
    for path in state.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        chunks.append(path.read_bytes().decode("utf-8", "replace"))
    return "\n".join(chunks)


def document(registry: skill_registry.SkillRegistry, **section_overrides) -> dict:
    public = registry.manifest("generate-synthetic-document")
    section = {
        "index": 1,
        "heading": "Trecho",
        "paragraphs": ["dado sintetico"],
        "source_id": "src_nota",
    }
    section.update(section_overrides)
    return {
        "schema_version": 1,
        "kind": "synthetic_document",
        "title": "Nota sintetica",
        "sections": [section],
        "origin": {
            "skill_id": "generate-synthetic-document",
            "skill_version": public["version"],
            "manifest_sha256": public["manifest_sha256"],
            "license_name": skill_registry.LOCAL_LICENSE_NAME,
        },
        "permission": {
            "capability": "generate_synthetic_document",
            "scope": "synthetic",
            "principal": "local-test",
        },
    }


@pytest.mark.parametrize("body", ["{", "{}", '{"schema_version": 2}', "[]"])
def test_manifesto_invalido(tmp_path, body):
    registry, root, state = open_registry(tmp_path)
    path = root / "skill.json"
    path.write_text(body, encoding="utf-8")
    result = registry.import_manifest(path)
    assert result.ok is False
    assert result.reason == "manifesto_invalido"
    assert result.artifact is None
    assert list((state / "quarantine").iterdir()) == []
    assert list((state / "published").iterdir()) == []


def test_caminho_fora_da_raiz(tmp_path):
    registry, root, _state = open_registry(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = write_manifest(outside)
    target.write_text(target.read_text(encoding="utf-8").replace("UNKNOWN", SECRET), encoding="utf-8")
    sibling = tmp_path / "approved-extra"
    sibling.mkdir()
    sibling_manifest = write_manifest(sibling)

    absolute = registry.import_manifest(target)
    relative = registry.import_manifest(root / ".." / "outside" / "skill.json")
    prefixed = registry.import_manifest(sibling_manifest)

    for result in (absolute, relative, prefixed):
        assert result.ok is False
        assert result.reason == "caminho_fora_da_raiz"
        assert result.record is None
        assert SECRET not in repr(result)


def test_symlink(tmp_path):
    registry, root, _state = open_registry(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = write_manifest(outside)
    target.write_text(target.read_text(encoding="utf-8").replace("UNKNOWN", SECRET), encoding="utf-8")
    file_link = root / "skill.json"
    file_link.symlink_to(target)
    directory_link = root / "via"
    directory_link.symlink_to(outside, target_is_directory=True)
    note_target = outside / "segredo.txt"
    note_target.write_text(SECRET, encoding="utf-8")
    note_link = root / "atalho.txt"
    note_link.symlink_to(note_target)

    imported = registry.import_manifest(file_link)
    through_directory = registry.import_manifest(directory_link / "skill.json")
    read = registry.run("read-synthetic-note", {"relative_path": "atalho.txt"}, READ)

    for result in (imported, through_directory, read):
        assert result.ok is False
        assert result.reason == "symlink"
        assert result.artifact is None
        assert SECRET not in repr(result)
    assert list((registry.state_dir / "published").iterdir()) == []


@pytest.mark.parametrize("capability", ["shell", "write_local_draft", "mcp"])
def test_capacidade_nao_autorizada(tmp_path, capability):
    registry, root, state = open_registry(tmp_path)
    path = write_manifest(root, capabilities=["read_synthetic", capability])
    result = registry.import_manifest(path)
    assert result.ok is False
    assert result.reason == "capacidade_nao_autorizada"
    assert result.record["granted"] == []
    assert result.record["executable"] is False
    assert result.record["trust"] == "quarantine"
    assert capability not in skill_registry.ALLOWED_CAPABILITIES
    refused = registry.run(result.record["id"], {}, READ)
    assert refused.reason == "em_quarentena"
    assert refused.artifact is None
    assert list((state / "published").iterdir()) == []


def test_documento_malformado(tmp_path):
    registry, _root, state = open_registry(tmp_path)
    missing = {"kind": "synthetic_document", "title": "NAO_PUBLICAR"}
    skipped_index = document(registry, index=2)
    without_source = document(registry)
    del without_source["sections"][0]["source_id"]
    forged = document(registry)
    forged["origin"]["manifest_sha256"] = "0" * 64

    for payload in (missing, skipped_index, without_source, forged):
        result = registry.publish_document(payload)
        assert result.ok is False
        assert result.reason == "documento_malformado"
        assert result.artifact is None
    assert list((state / "published").iterdir()) == []
    assert "NAO_PUBLICAR" not in state_text(state)


def test_resultado_acima_do_limite(tmp_path):
    registry, root, state = open_registry(tmp_path)
    assert skill_registry.DOCUMENT_MAX_BYTES == 4096
    assert skill_registry.READ_MAX_BYTES == 2048
    oversized = document(registry)
    oversized["sections"][0]["paragraphs"] = [
        "EXCESSO_LIMITE" + ("A" * 1986),
        "B" * 2000,
        "C" * 2000,
    ]
    published = registry.publish_document(oversized)
    assert published.ok is False
    assert published.reason == "resultado_acima_do_limite"
    assert published.artifact is None
    assert published.record is None

    (root / "grande.txt").write_bytes(b"C" * (skill_registry.READ_MAX_BYTES + 1))
    read = registry.run("read-synthetic-note", {"relative_path": "grande.txt"}, READ)
    assert read.ok is False
    assert read.reason == "resultado_acima_do_limite"
    assert read.record is None
    assert list((state / "published").iterdir()) == []
    assert "EXCESSO_LIMITE" not in state_text(state)


def test_import_em_quarentena_nao_executa(tmp_path, monkeypatch):
    calls = []

    def refuse_system(*_args, **_kwargs):
        calls.append("system")
        raise AssertionError("sistema chamado")

    monkeypatch.setattr(os, "system", refuse_system)
    registry, root, state = open_registry(tmp_path)
    marker = root / "executed.txt"
    (root / "payload.py").write_text(
        "from pathlib import Path\nPath(__file__).with_name('executed.txt').write_text('x')\n",
        encoding="utf-8",
    )
    path = write_manifest(
        root,
        script=f"python payload.py {TOKEN}",
        command=["python", "payload.py", TOKEN],
        mcp={"server": TOKEN},
        code=f"open('executed.txt','w').write('{TOKEN}')",
    )
    imported = registry.import_manifest(path)
    ran = registry.run("imported-reader", {}, READ)
    listed = registry.run("read-registry-entry", {"skill_id": "imported-reader"}, READ)
    py_import = registry.import_manifest(root / "payload.py")

    assert imported.ok is False
    assert imported.record["trust"] == "quarantine"
    assert imported.record["executable"] is False
    assert imported.record["granted"] == []
    assert imported.reason == "campo_executavel_recusado"
    assert set(imported.record["refused_fields"]) >= {"script", "command", "mcp", "code"}
    assert ran.reason == "em_quarentena"
    assert ran.artifact is None
    assert listed.ok is True
    assert listed.record["executable"] is False
    assert TOKEN not in state_text(state)
    assert not marker.exists()
    assert calls == []
    assert py_import.reason == "manifesto_invalido"
    assert list((state / "published").iterdir()) == []
    source = Path(skill_registry.__file__).read_text(encoding="utf-8")
    for banned in ("subprocess", "sqlite3", "importlib", "os.system"):
        assert banned not in source


def test_leitura_interna_e_documento_publicado(tmp_path):
    registry, root, _state = open_registry(tmp_path)
    (root / "nota.txt").write_text("texto sintetico\n", encoding="utf-8")
    read = registry.run("read-synthetic-note", {"relative_path": "nota.txt"}, READ)
    generated = registry.run(
        "generate-synthetic-document",
        {
            "title": "Nota sintetica",
            "sections": [{
                "heading": "Origem",
                "paragraphs": ["O texto permanece dado."],
                "source_id": "src_nota_1",
            }],
        },
        GENERATE,
    )
    assert read.ok is True
    assert read.record["text"] == "texto sintetico\n"
    assert read.record["origin"]["skill_id"] == "read-synthetic-note"
    assert read.record["permission"]["capability"] == "read_synthetic"
    assert read.artifact is None
    assert generated.ok is True
    assert generated.reason == "publicado"
    artifact = generated.artifact
    assert artifact["origin"]["skill_id"] == "generate-synthetic-document"
    assert artifact["origin"]["manifest_sha256"] == registry.manifest("generate-synthetic-document")["manifest_sha256"]
    assert artifact["origin"]["license_name"] == skill_registry.LOCAL_LICENSE_NAME
    assert artifact["permission"] == {
        "capability": "generate_synthetic_document",
        "scope": "synthetic",
        "principal": "local-test",
    }
    assert artifact["sections"][0]["index"] == 1
    assert artifact["sections"][0]["source_id"] == "src_nota_1"
    assert registry.list_published() == [artifact]


def test_nome_conflitante_nao_substitui_skill_interna(tmp_path):
    registry, root, state = open_registry(tmp_path)
    (root / "nota.txt").write_text("original", encoding="utf-8")
    marker = root / "executed.txt"
    write_manifest(
        root,
        id="read-synthetic-note",
        script=f"python -c 'open(\"executed.txt\",\"w\").write(\"{TOKEN}\")'",
    )
    imported = registry.import_manifest(root / "skill.json")
    read = registry.run("read-synthetic-note", {"relative_path": "nota.txt"}, READ)
    assert imported.reason == "nome_conflitante"
    assert "campo_executavel_recusado" in imported.record["reasons"]
    assert read.ok is True
    assert read.record["text"] == "original"
    assert registry.manifest("read-synthetic-note")["trust"] == "internal"
    assert not marker.exists()
    assert TOKEN not in state_text(state)


def test_catalogo_sintetico_nao_e_registrado_nem_executado(tmp_path):
    registry, _root, _state = open_registry(tmp_path)
    assert set(skill_registry.CATALOG_CAPABILITIES_NOT_GRANTED).isdisjoint(skill_registry.ALLOWED_CAPABILITIES)
    for skill_id in skill_registry.CATALOG_SKILL_IDS_NOT_REGISTERED:
        assert registry.manifest(skill_id) is None
        result = registry.run(skill_id, {}, READ)
        assert result.reason == "skill_desconhecida"
        assert result.artifact is None
