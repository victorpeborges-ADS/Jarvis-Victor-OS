"""Contrato DEMO v1.

domain_id classifica a memória. Não autoriza leitura.
Gate 2+ precisará impor autorização no servidor antes de qualquer fonte real.
Este módulo não abre OAuth nem conectores externos.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator
from pydantic import BaseModel, ConfigDict, ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "demo.json"
SCHEMA = ROOT / "contracts" / "jarvis.demo.v1.schema.json"


class ProvenanceOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    origin: str
    last_checked: str
    confidence: str
    url: str | None = None
    scope: str | None = None
    note: str | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    title: str
    event_type: str
    sensitivity: str
    occurred_at: str
    source_id: str
    domain_id: str | None = None
    show_in_agora: bool | None = None
    provenance: ProvenanceOut


class CaptureOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    domain_id: str
    type: str
    title: str
    status: str
    created_at: str
    evidence: str
    entity_ref: str | None = None


class DomainOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    count: int | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    provider: str
    sync_status: str


class HealthOut(BaseModel):
    status: str
    gate: int
    mode: str
    demo: bool


class FixtureError(Exception):
    pass


def schema_document() -> dict:
    return json.loads(SCHEMA.read_text())


def _validator(definition: str) -> Draft7Validator:
    document = schema_document()
    registry = Registry().with_resource(document["$id"], Resource.from_contents(document))
    return Draft7Validator({"$ref": f"{document['$id']}#/definitions/{definition}"}, registry=registry)


def read_raw_fixture() -> dict:
    try:
        data = json.loads(FIXTURES.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureError("fixture DEMO ilegível") from exc
    if not isinstance(data, dict):
        raise FixtureError("fixture DEMO inválida")
    return data


def parse_collection(raw: object, model: type[BaseModel], definition: str) -> list:
    if not isinstance(raw, list):
        return []
    validator = _validator(definition)
    parsed = []
    for item in raw:
        if list(validator.iter_errors(item)):
            continue
        try:
            parsed.append(model.model_validate(item))
        except ValidationError:
            continue
    return parsed
