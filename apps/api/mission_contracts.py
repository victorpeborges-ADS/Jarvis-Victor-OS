"""Versioned Mission contracts shared with the web client through JSON Schema."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "jarvis.missions.v1.schema.json"
EXAMPLES_PATH = ROOT / "contracts" / "jarvis.missions.v1.examples.json"


def contract_examples() -> dict[str, object]:
    return json.loads(EXAMPLES_PATH.read_text())


def validate_contract(name: str, value: object) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    if name not in schema["$defs"]:
        raise ValueError("contrato desconhecido")
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/{name}"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    errors = list(validator.iter_errors(value))
    if errors:
        raise ValueError("; ".join(error.message for error in errors))


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MissionTask(StrictContract):
    id: str = Field(pattern=r"^task_[A-Za-z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=240)
    status: Literal["draft", "planned", "awaiting_approval", "running", "blocked", "done", "cancelled", "failed"]
    depends_on: tuple[str, ...]
    attempt: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=160)
    updated_at: datetime
    failure_reason: str | None = Field(default=None, max_length=500)

    @field_validator("updated_at")
    @classmethod
    def updated_at_needs_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp precisa de fuso horário")
        return value


class Mission(StrictContract):
    schema_version: Literal[1]
    id: str = Field(pattern=r"^mission_[A-Za-z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    status: Literal["draft", "planned", "awaiting_approval", "running", "blocked", "done", "cancelled", "failed"]
    domain_id: str | None
    tasks: tuple[MissionTask, ...]
    checkpoints: tuple[dict, ...]
    artifacts: tuple[dict, ...]
    budget: dict
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_need_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp precisa de fuso horário")
        return value
