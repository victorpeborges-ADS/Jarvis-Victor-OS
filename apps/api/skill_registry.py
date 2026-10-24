"""Registro local de skills e publicação de documento sintético.

Importar, ler ou registrar um manifesto não executa script, comando, MCP
nem código trazido pela skill. A allowlist de capacidades é fechada.
Um documento só é gravado em ``published`` depois da validação de esquema,
origem, permissão e tamanho. Este módulo não abre banco e não escreve fora
dos diretórios recebidos do chamador.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

MANIFEST_SCHEMA_VERSION = 1
DOCUMENT_SCHEMA_VERSION = 1
DOCUMENT_MAX_BYTES = 4096
MANIFEST_MAX_BYTES = 8192
READ_MAX_BYTES = 2048
LOCAL_LICENSE_NAME = "nao-declarada-no-arquivo-local"
CONTRACT_REFERENCE = "apps/web/lib/skill-catalog.ts"

# Capacidades do catálogo sintético que este registro não concede e não executa.
CATALOG_CAPABILITIES_NOT_GRANTED = (
    "write_local_draft",
    "build_context",
    "compare_sources",
)
CATALOG_SKILL_IDS_NOT_REGISTERED = (
    "capture-and-classify",
    "build-context",
    "draft-evidenced-report",
    "compare-sources",
)

ALLOWED_CAPABILITIES = frozenset({
    "read_synthetic",
    "generate_synthetic_document",
})
FORBIDDEN_FIELDS = frozenset({
    "script",
    "command",
    "entrypoint",
    "entry",
    "mcp",
    "code",
    "shell",
    "run",
    "install",
    "module",
    "handler",
    "args",
    "cmd",
    "executable",
    "bin",
    "main",
})
_SKILL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9_-]{1,80}\Z")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _plain(value: str, *, newlines: bool = False) -> bool:
    for char in value:
        if newlines and char in "\n\t":
            continue
        code = ord(char)
        if code < 32 or code == 127:
            return False
    return True


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _local_object_schema(schema: object) -> bool:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    if schema.get("additionalProperties") is not False or _contains_key(schema, "$ref"):
        return False
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return False
    return True


def _validator(schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


_OBJECT = {"type": "object", "additionalProperties": False}

MANIFEST_SCHEMA = {
    **_OBJECT,
    "required": [
        "schema_version",
        "id",
        "version",
        "origin",
        "license",
        "purpose",
        "capabilities",
        "inputs",
        "outputs",
        "side_effects",
        "privacy",
    ],
    "properties": {
        "schema_version": {"const": MANIFEST_SCHEMA_VERSION},
        "id": {"type": "string", "pattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$", "maxLength": 64},
        "version": {"type": "string", "pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$"},
        "origin": {
            **_OBJECT,
            "required": ["kind", "ref"],
            "properties": {
                "kind": {"enum": ["internal", "imported"]},
                "ref": {"type": "string", "minLength": 1, "maxLength": 200},
            },
        },
        "license": {
            **_OBJECT,
            "required": ["name", "spdx"],
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "spdx": {"type": ["string", "null"], "maxLength": 80},
            },
        },
        "purpose": {"type": "string", "minLength": 1, "maxLength": 400},
        "capabilities": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "inputs": {"type": "object"},
        "outputs": {"type": "object"},
        "side_effects": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"enum": ["none", "local_draft"]},
        },
        "privacy": {"const": "synthetic_only"},
    },
}

NOTE_INPUT_SCHEMA = {
    **_OBJECT,
    "required": ["relative_path"],
    "properties": {
        "relative_path": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,40}){0,4}\.(?:txt|md)$",
        },
    },
}

REGISTRY_INPUT_SCHEMA = {
    **_OBJECT,
    "required": ["skill_id"],
    "properties": {
        "skill_id": {"type": "string", "pattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$", "maxLength": 64},
    },
}

DOCUMENT_INPUT_SCHEMA = {
    **_OBJECT,
    "required": ["title", "sections"],
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
        "sections": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                **_OBJECT,
                "required": ["heading", "paragraphs", "source_id"],
                "properties": {
                    "heading": {"type": "string", "minLength": 1, "maxLength": 80},
                    "paragraphs": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {"type": "string", "minLength": 1, "maxLength": 400},
                    },
                    "source_id": {"type": "string", "pattern": r"^src_[a-z0-9_]{1,40}$"},
                },
            },
        },
    },
}

_ORIGIN_SCHEMA = {
    **_OBJECT,
    "required": ["skill_id", "skill_version", "manifest_sha256", "license_name"],
    "properties": {
        "skill_id": {"type": "string"},
        "skill_version": {"type": "string"},
        "manifest_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
        "license_name": {"type": "string"},
    },
}
_PERMISSION_SCHEMA = {
    **_OBJECT,
    "required": ["capability", "scope", "principal"],
    "properties": {
        "capability": {"type": "string"},
        "scope": {"const": "synthetic"},
        "principal": {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,80}$"},
    },
}

NOTE_OUTPUT_SCHEMA = {
    **_OBJECT,
    "required": ["relative_path", "sha256", "byte_length", "text", "origin", "permission"],
    "properties": {
        "relative_path": {"type": "string"},
        "sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
        "byte_length": {"type": "integer", "minimum": 0, "maximum": READ_MAX_BYTES},
        "text": {"type": "string", "maxLength": READ_MAX_BYTES},
        "origin": _ORIGIN_SCHEMA,
        "permission": _PERMISSION_SCHEMA,
    },
}

REGISTRY_OUTPUT_SCHEMA = {
    **_OBJECT,
    "required": [
        "id",
        "version",
        "trust",
        "origin",
        "license_name",
        "capabilities",
        "executable",
        "manifest_sha256",
    ],
    "properties": {
        "id": {"type": "string"},
        "version": {"type": "string"},
        "trust": {"enum": ["internal", "quarantine"]},
        "origin": {
            **_OBJECT,
            "required": ["kind", "ref"],
            "properties": {
                "kind": {"enum": ["internal", "imported"]},
                "ref": {"type": "string"},
            },
        },
        "license_name": {"type": "string"},
        "capabilities": {"type": "array", "items": {"type": "string"}},
        "granted": {"type": "array", "items": {"type": "string"}},
        "executable": {"const": False},
        "manifest_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
        "reason": {"type": "string"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "refused_fields": {"type": "array", "items": {"type": "string"}},
        "purpose": {"type": "string"},
    },
}

DOCUMENT_SCHEMA = {
    **_OBJECT,
    "required": ["schema_version", "kind", "title", "sections", "origin", "permission"],
    "properties": {
        "schema_version": {"const": DOCUMENT_SCHEMA_VERSION},
        "kind": {"const": "synthetic_document"},
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
        "sections": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                **_OBJECT,
                "required": ["index", "heading", "paragraphs", "source_id"],
                "properties": {
                    "index": {"type": "integer", "minimum": 1},
                    "heading": {"type": "string", "minLength": 1, "maxLength": 80},
                    "paragraphs": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2000},
                    },
                    "source_id": {"type": "string", "pattern": r"^src_[a-z0-9_]{1,40}$"},
                },
            },
        },
        "origin": _ORIGIN_SCHEMA,
        "permission": _PERMISSION_SCHEMA,
    },
}


def _license(name: str = LOCAL_LICENSE_NAME) -> dict:
    return {"name": name, "spdx": None}


def _manifest(
    skill_id: str,
    purpose: str,
    capabilities: list[str],
    inputs: dict,
    outputs: dict,
    side_effects: list[str],
) -> dict:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "id": skill_id,
        "version": "1.0.0",
        "origin": {"kind": "internal", "ref": f"apps/api/skill_registry.py#{skill_id}"},
        "license": _license(),
        "purpose": purpose,
        "capabilities": capabilities,
        "inputs": inputs,
        "outputs": outputs,
        "side_effects": side_effects,
        "privacy": "synthetic_only",
    }


INTERNAL_MANIFESTS = (
    _manifest(
        "read-synthetic-note",
        "Ler um texto sintético .txt ou .md dentro da raiz aprovada e devolvê-lo como dado.",
        ["read_synthetic"],
        NOTE_INPUT_SCHEMA,
        NOTE_OUTPUT_SCHEMA,
        ["none"],
    ),
    _manifest(
        "read-registry-entry",
        "Ler o registro público de uma skill sem executar código declarado por ela.",
        ["read_synthetic"],
        REGISTRY_INPUT_SCHEMA,
        REGISTRY_OUTPUT_SCHEMA,
        ["none"],
    ),
    _manifest(
        "generate-synthetic-document",
        "Gerar um documento sintético estruturado e publicá-lo só depois da validação.",
        ["generate_synthetic_document"],
        DOCUMENT_INPUT_SCHEMA,
        DOCUMENT_SCHEMA,
        ["local_draft"],
    ),
)


@dataclass(frozen=True)
class Permission:
    capability: str
    scope: str
    principal: str


@dataclass(frozen=True)
class SkillResult:
    ok: bool
    reason: str
    record: dict | None = None
    artifact: dict | None = None


def _fail(reason: str, record: dict | None = None) -> SkillResult:
    return SkillResult(False, reason, record, None)


class SkillRegistry:
    """Skills internas são dados deste módulo. Importação de arquivo fica em quarentena."""

    def __init__(self, approved_root: Path, state_dir: Path) -> None:
        self.approved_root = _require_distinct_dir(approved_root, state_dir)
        self.state_dir = _require_distinct_dir(state_dir, approved_root)
        self._internal: dict[str, dict] = {}
        self._hashes: dict[str, str] = {}
        self._input_validators: dict[str, Draft202012Validator] = {}
        self._output_validators: dict[str, Draft202012Validator] = {}
        self._quarantine: dict[str, dict] = {}
        for name in ("skills", "quarantine", "published"):
            _mkdir_real(self.state_dir / name)
        for manifest in INTERNAL_MANIFESTS:
            self._install_internal(manifest)

    def manifest(self, skill_id: str) -> dict | None:
        if skill_id in self._internal:
            return json.loads(canonical_json(self._public_internal(skill_id)))
        return json.loads(canonical_json(self._quarantine[skill_id])) if skill_id in self._quarantine else None

    def trusted_manifest_sha256(self, skill_id: str) -> str:
        """Return a digest only for a bundled, server-owned internal skill."""
        if skill_id not in self._internal:
            return ""
        return self._hashes[skill_id]

    def import_manifest(self, candidate: Path) -> SkillResult:
        located = _locate(self.approved_root, candidate, ".json")
        if isinstance(located, str):
            return _fail(located if located != "arquivo_ausente" else "manifesto_invalido")
        blob = _read_limited(located, MANIFEST_MAX_BYTES)
        if isinstance(blob, str):
            return _fail("manifesto_acima_do_limite" if blob == "acima_do_limite" else "manifesto_invalido")
        try:
            data = json.loads(blob.decode("utf-8"))
        except (UnicodeError, ValueError):
            return _fail("manifesto_invalido")
        if not isinstance(data, dict):
            return _fail("manifesto_invalido")
        refused = sorted(FORBIDDEN_FIELDS.intersection(data))
        clean = {key: value for key, value in data.items() if key not in FORBIDDEN_FIELDS}
        if list(_validator(MANIFEST_SCHEMA).iter_errors(clean)):
            return _fail("manifesto_invalido")
        if not _local_object_schema(clean["inputs"]) or not _local_object_schema(clean["outputs"]):
            return _fail("manifesto_invalido")
        spdx = clean["license"]["spdx"]
        if not _plain(clean["purpose"]) or not _plain(clean["license"]["name"]) or (spdx is not None and not _plain(spdx)):
            return _fail("manifesto_invalido")
        capabilities = list(clean["capabilities"])
        if len(capabilities) != len(set(capabilities)):
            return _fail("manifesto_invalido")
        relative = located.relative_to(self.approved_root).as_posix()
        reasons: list[str] = []
        if not set(capabilities) <= ALLOWED_CAPABILITIES:
            reasons.append("capacidade_nao_autorizada")
        if clean["id"] in self._internal:
            reasons.append("nome_conflitante")
        if refused:
            reasons.append("campo_executavel_recusado")
        if not reasons:
            reasons.append("importacao_nao_confiavel")
        record = {
            "id": clean["id"],
            "version": clean["version"],
            "trust": "quarantine",
            "origin": {"kind": "imported", "ref": relative},
            "license_name": clean["license"]["name"],
            "capabilities": capabilities,
            "granted": [],
            "executable": False,
            "manifest_sha256": _sha256_bytes(blob),
            "reason": reasons[0],
            "reasons": reasons,
            "refused_fields": refused,
            "purpose": clean["purpose"],
        }
        self._store_quarantine(record)
        return _fail(reasons[0], record)

    def run(self, skill_id: str, payload: dict, permission: Permission) -> SkillResult:
        if not isinstance(payload, dict):
            return _fail("entrada_invalida")
        if permission.scope != "synthetic" or _PRINCIPAL.fullmatch(permission.principal) is None:
            return _fail("escopo_recusado")
        if permission.capability not in ALLOWED_CAPABILITIES:
            return _fail("capacidade_nao_autorizada")
        if skill_id not in self._internal:
            if skill_id in self._quarantine:
                return _fail("em_quarentena", self.manifest(skill_id))
            return _fail("skill_desconhecida")
        manifest = self._internal[skill_id]
        if permission.capability not in manifest["capabilities"]:
            return _fail("capacidade_nao_autorizada")
        if list(self._input_validators[skill_id].iter_errors(payload)):
            return _fail("entrada_invalida")
        if skill_id == "read-synthetic-note":
            output = self._read_note(payload, permission)
        elif skill_id == "read-registry-entry":
            output = self._read_entry(payload)
        elif skill_id == "generate-synthetic-document":
            output = self._generate(payload, permission)
        else:
            return _fail("skill_desconhecida")
        if isinstance(output, SkillResult):
            return output
        if list(self._output_validators[skill_id].iter_errors(output)):
            return _fail("saida_invalida")
        return SkillResult(True, "lido", output, None)

    def publish_document(self, document: dict) -> SkillResult:
        if not isinstance(document, dict) or list(_validator(DOCUMENT_SCHEMA).iter_errors(document)):
            return _fail("documento_malformado")
        sections = document["sections"]
        for index, section in enumerate(sections, start=1):
            if section["index"] != index:
                return _fail("documento_malformado")
        strings = [document["title"], *(section["heading"] for section in sections)]
        strings.extend(paragraph for section in sections for paragraph in section["paragraphs"])
        if not all(isinstance(item, str) and _plain(item) for item in strings):
            return _fail("documento_malformado")
        origin = document["origin"]
        expected = self._hashes.get("generate-synthetic-document")
        if (
            origin["skill_id"] != "generate-synthetic-document"
            or origin["skill_version"] != self._internal["generate-synthetic-document"]["version"]
            or origin["manifest_sha256"] != expected
            or origin["license_name"] != LOCAL_LICENSE_NAME
        ):
            return _fail("documento_malformado")
        permission = document["permission"]
        if permission["capability"] != "generate_synthetic_document":
            return _fail("capacidade_nao_autorizada")
        artifact = {**document, "id": "doc_" + _sha256_text(canonical_json(document))[:16]}
        encoded = canonical_json(artifact).encode("utf-8")
        if len(encoded) > DOCUMENT_MAX_BYTES:
            return _fail("resultado_acima_do_limite")
        path = self.state_dir / "published" / f"{artifact['id']}.json"
        if not _write_exclusive(path, encoded):
            return _fail("documento_malformado")
        return SkillResult(True, "publicado", None, json.loads(encoded.decode("utf-8")))

    def list_published(self) -> list[dict]:
        directory = self.state_dir / "published"
        if directory.is_symlink() or not directory.is_dir():
            return []
        items = []
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                continue
            blob = _read_limited(path, DOCUMENT_MAX_BYTES)
            if isinstance(blob, str):
                continue
            try:
                item = json.loads(blob.decode("utf-8"))
            except (UnicodeError, ValueError):
                continue
            if isinstance(item, dict) and item.get("kind") == "synthetic_document":
                items.append(item)
        return items

    def _install_internal(self, manifest: dict) -> None:
        if list(_validator(MANIFEST_SCHEMA).iter_errors(manifest)):
            raise RuntimeError("manifesto interno invalido")
        if not set(manifest["capabilities"]) <= ALLOWED_CAPABILITIES:
            raise RuntimeError("capacidade interna fora da allowlist")
        skill_id = manifest["id"]
        digest = _sha256_text(canonical_json(manifest))
        self._internal[skill_id] = manifest
        self._hashes[skill_id] = digest
        self._input_validators[skill_id] = _validator(manifest["inputs"])
        self._output_validators[skill_id] = _validator(manifest["outputs"])
        _write_exclusive(
            self.state_dir / "skills" / f"{skill_id}.json",
            canonical_json(self._public_internal(skill_id)).encode("utf-8"),
        )

    def _public_internal(self, skill_id: str) -> dict:
        manifest = self._internal[skill_id]
        return {
            "id": manifest["id"],
            "version": manifest["version"],
            "trust": "internal",
            "origin": manifest["origin"],
            "license_name": manifest["license"]["name"],
            "capabilities": list(manifest["capabilities"]),
            "granted": list(manifest["capabilities"]),
            "executable": False,
            "manifest_sha256": self._hashes[skill_id],
            "purpose": manifest["purpose"],
            "refused_fields": [],
        }

    def _store_quarantine(self, record: dict) -> None:
        self._quarantine[record["id"]] = record
        _write_exclusive(
            self.state_dir / "quarantine" / f"{record['manifest_sha256']}.json",
            canonical_json(record).encode("utf-8"),
        )

    def _origin_for(self, skill_id: str) -> dict:
        manifest = self._internal[skill_id]
        return {
            "skill_id": skill_id,
            "skill_version": manifest["version"],
            "manifest_sha256": self._hashes[skill_id],
            "license_name": manifest["license"]["name"],
        }

    def _permission_view(self, permission: Permission) -> dict:
        return {
            "capability": permission.capability,
            "scope": permission.scope,
            "principal": permission.principal,
        }

    def _read_note(self, payload: dict, permission: Permission) -> dict | SkillResult:
        located = _locate(self.approved_root, Path(payload["relative_path"]), ".txt", ".md")
        if isinstance(located, str):
            if located in {"symlink", "caminho_fora_da_raiz"}:
                return _fail(located)
            return _fail("entrada_invalida")
        blob = _read_limited(located, READ_MAX_BYTES)
        if isinstance(blob, str):
            return _fail("resultado_acima_do_limite" if blob == "acima_do_limite" else "entrada_invalida")
        try:
            text = blob.decode("utf-8")
        except UnicodeError:
            return _fail("entrada_invalida")
        if not _plain(text, newlines=True):
            return _fail("entrada_invalida")
        return {
            "relative_path": located.relative_to(self.approved_root).as_posix(),
            "sha256": _sha256_bytes(blob),
            "byte_length": len(blob),
            "text": text,
            "origin": self._origin_for("read-synthetic-note"),
            "permission": self._permission_view(permission),
        }

    def _read_entry(self, payload: dict) -> dict | SkillResult:
        view = self.manifest(payload["skill_id"])
        if view is None:
            return _fail("skill_desconhecida")
        return view

    def _generate(self, payload: dict, permission: Permission) -> SkillResult:
        title = payload["title"]
        if not _plain(title) or not title.strip():
            return _fail("entrada_invalida")
        sections = []
        for index, section in enumerate(payload["sections"], start=1):
            heading = section["heading"]
            paragraphs = list(section["paragraphs"])
            if not _plain(heading) or not heading.strip() or not all(_plain(item) for item in paragraphs):
                return _fail("entrada_invalida")
            sections.append({
                "index": index,
                "heading": heading,
                "paragraphs": paragraphs,
                "source_id": section["source_id"],
            })
        document = {
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "kind": "synthetic_document",
            "title": title,
            "sections": sections,
            "origin": self._origin_for("generate-synthetic-document"),
            "permission": self._permission_view(permission),
        }
        return self.publish_document(document)


def _require_distinct_dir(path: Path, other: Path) -> Path:
    if path.is_symlink() or other.is_symlink() or not path.is_dir() or not other.is_dir():
        raise ValueError("raiz_invalida")
    first = os.path.abspath(path)
    second = os.path.abspath(other)
    try:
        shared = os.path.commonpath([first, second])
    except ValueError as error:
        raise ValueError("raiz_invalida") from error
    if first == second or shared in {first, second}:
        raise ValueError("raiz_invalida")
    return Path(first)


def _mkdir_real(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("symlink")
    path.mkdir(exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("symlink")


def _locate(root: Path, candidate: Path, *suffixes: str) -> Path | str:
    raw = candidate if candidate.is_absolute() else root / candidate
    root_abs = os.path.abspath(root)
    candidate_abs = os.path.abspath(raw)
    try:
        if os.path.commonpath([root_abs, candidate_abs]) != root_abs:
            return "caminho_fora_da_raiz"
    except ValueError:
        return "caminho_fora_da_raiz"
    relative = os.path.relpath(candidate_abs, root_abs)
    if relative.startswith(".."):
        return "caminho_fora_da_raiz"
    current = Path(root_abs)
    if current.is_symlink():
        return "symlink"
    parts = Path(relative).parts
    if not parts or parts == (".",):
        return "arquivo_ausente"
    for part in parts:
        if part in {"", ".", ".."}:
            return "caminho_fora_da_raiz"
        current = current / part
        if current.is_symlink():
            return "symlink"
        if not current.exists():
            return "arquivo_ausente"
    info = current.lstat()
    if not stat.S_ISREG(info.st_mode):
        return "arquivo_ausente"
    if suffixes and current.suffix not in suffixes:
        return "arquivo_ausente"
    return current


def _read_limited(path: Path, limit: int) -> bytes | str:
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    except OSError:
        return "symlink" if path.is_symlink() else "leitura_recusada"
    try:
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            block = os.read(fd, remaining)
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        blob = b"".join(chunks)
    finally:
        os.close(fd)
    if len(blob) > limit:
        return "acima_do_limite"
    return blob


def _write_exclusive(path: Path, payload: bytes) -> bool:
    if path.is_symlink() or path.parent.is_symlink():
        return False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        existing = _read_limited(path, len(payload))
        return existing == payload
    except OSError:
        return False
    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                return False
            offset += written
    finally:
        os.close(fd)
    return True
