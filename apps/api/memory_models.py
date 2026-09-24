"""Validated data contracts for the local memory store.

These models describe persisted records. They do not grant access; reads still
require the volatile server session and grant checks in ``local_security``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from domain_registry import CANONICAL_CONNECTORS, CANONICAL_DOMAIN_IDS, CANONICAL_RESOURCES


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp precisa de fuso horário")
    return value


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRecord(StrictRecord):
    id: str = Field(min_length=1, max_length=128)
    provider: str
    resource_id: str
    account_ref: str | None = Field(default=None, max_length=256)
    scopes: tuple[str, ...] = ()
    sync_status: Literal["disconnected", "idle", "syncing", "stale", "error", "revoked"] = "disconnected"
    dataset: Literal["real"] = "real"
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("id")
    @classmethod
    def id_is_safe(cls, value: str) -> str:
        if any(char.isspace() for char in value) or "\x00" in value:
            raise ValueError("source id inválido")
        return value

    @field_validator("provider")
    @classmethod
    def provider_is_canonical(cls, value: str) -> str:
        if value not in CANONICAL_CONNECTORS:
            raise ValueError("conector desconhecido")
        return value

    @field_validator("resource_id")
    @classmethod
    def resource_is_canonical(cls, value: str, info) -> str:
        provider = info.data.get("provider")
        if value not in CANONICAL_RESOURCES.get(provider, frozenset()):
            raise ValueError("recurso desconhecido")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)  # type: ignore[return-value]


class ProvenanceRecord(StrictRecord):
    source_id: str
    external_ref: str | None = Field(default=None, max_length=512)
    observed_at: datetime
    last_verified_at: datetime | None = None
    valid_until: datetime | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    classification_method: Literal["human_review", "explicit_rule", "unclassified"] = "unclassified"
    classified_at: datetime | None = None

    @field_validator("observed_at", "last_verified_at", "valid_until", "classified_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value)


class AuditRecord(StrictRecord):
    """Minimal operational audit fact; excludes record and user content."""

    operation: Literal["source_write", "event_write", "entity_write", "relation_write", "memory_read"]
    outcome: Literal["success"] = "success"
    record_count: int = Field(default=0, ge=0)
    dataset: Literal["real"] = "real"
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)  # type: ignore[return-value]


class EventRecord(StrictRecord):
    id: str = Field(min_length=11, max_length=128, pattern=r"^real_evt_[A-Za-z0-9_-]+$")
    event_type: Literal["appointment", "task", "message", "note", "reference", "project"]
    title: str = Field(min_length=1, max_length=500)
    domain_id: str | None = None
    sensitivity: Literal["normal", "sensitive", "restricted"] = "normal"
    occurred_at: datetime | None = None
    cancelled_at: datetime | None = None
    payload_minimized: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceRecord
    dataset: Literal["real"] = "real"
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("id")
    @classmethod
    def id_is_safe(cls, value: str) -> str:
        if not value.startswith("real_evt_") or any(char.isspace() for char in value) or "\x00" in value:
            raise ValueError("event id precisa do namespace real_evt_")
        return value

    @field_validator("domain_id")
    @classmethod
    def domain_is_canonical_or_quarantined(cls, value: str | None) -> str | None:
        if value is not None and value not in CANONICAL_DOMAIN_IDS:
            raise ValueError("domain_id desconhecido")
        return value

    @field_validator("occurred_at", "cancelled_at", "created_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value)

    @model_validator(mode="after")
    def classification_has_provenance(self) -> EventRecord:
        if self.domain_id is None:
            if self.provenance.classification_method != "unclassified":
                raise ValueError("registro sem domínio precisa permanecer não classificado")
        elif self.provenance.classification_method == "unclassified" or self.provenance.classified_at is None:
            raise ValueError("classificação do domínio precisa de método e instante")
        return self


class CalendarSyncCheckpoint(StrictRecord):
    """Persisted mapping and opaque simulated-provider continuation state."""

    source_id: str = Field(min_length=1, max_length=128)
    calendar_id: str = Field(pattern=r"^sim_calendar_[a-h]$")
    domain_id: str | None = None
    classified_at: datetime | None = None
    sync_token: str | None = Field(default=None, max_length=512)
    page_token: str | None = Field(default=None, max_length=512)
    full_sync_id: str | None = Field(default=None, max_length=128)
    sync_status: Literal["simulated", "stale", "error"] = "simulated"
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    error_code: Literal["simulated_network", "invalid_cursor", "provider_error"] | None = None

    @field_validator("domain_id")
    @classmethod
    def domain_is_canonical(cls, value: str | None) -> str | None:
        if value is not None and value not in CANONICAL_DOMAIN_IDS:
            raise ValueError("domínio de calendário desconhecido")
        return value

    @field_validator("classified_at", "last_success_at", "last_attempt_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value)

    @model_validator(mode="after")
    def classification_is_complete(self) -> CalendarSyncCheckpoint:
        if (self.domain_id is None) != (self.classified_at is None):
            raise ValueError("classificação do calendário incompleta")
        if self.sync_status != "error" and self.error_code is not None:
            raise ValueError("estado sem erro não pode conter código de erro")
        return self


class EntityRecord(StrictRecord):
    id: str = Field(min_length=1, max_length=128)
    entity_type: Literal["person", "project", "task", "appointment", "document", "goal"]
    name: str = Field(min_length=1, max_length=300)
    domain_id: str | None = None
    sensitivity: Literal["normal", "sensitive", "restricted"] = "normal"
    dataset: Literal["real"] = "real"
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("domain_id")
    @classmethod
    def domain_is_canonical_or_quarantined(cls, value: str | None) -> str | None:
        if value is not None and value not in CANONICAL_DOMAIN_IDS:
            raise ValueError("domain_id desconhecido")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)  # type: ignore[return-value]


class RelationRecord(StrictRecord):
    id: str = Field(min_length=1, max_length=128)
    from_entity_id: str
    to_entity_id: str
    relation_type: Literal["related_to", "owns", "blocks", "supports", "scheduled_for", "mentions"]
    domain_id: str | None = None
    evidence_event_ids: tuple[str, ...] = ()
    review_status: Literal["pending", "accepted", "rejected"] = "pending"
    dataset: Literal["real"] = "real"
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def endpoints_must_differ(self) -> RelationRecord:
        if self.from_entity_id == self.to_entity_id:
            raise ValueError("relação não pode apontar para a mesma entidade")
        return self

    @field_validator("domain_id")
    @classmethod
    def domain_is_canonical_or_quarantined(cls, value: str | None) -> str | None:
        if value is not None and value not in CANONICAL_DOMAIN_IDS:
            raise ValueError("domain_id desconhecido")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)  # type: ignore[return-value]


class ReadScope(StrictRecord):
    """Minimum authorization predicate passed from grants to storage queries."""

    connector: Literal["calendar_sim"]
    resource_id: str
    domain_ids: frozenset[str]

    @field_validator("resource_id")
    @classmethod
    def resource_is_canonical(cls, value: str) -> str:
        if value not in CANONICAL_RESOURCES["calendar_sim"]:
            raise ValueError("recurso de leitura desconhecido")
        return value

    @field_validator("domain_ids")
    @classmethod
    def domains_are_canonical(cls, values: frozenset[str]) -> frozenset[str]:
        if not values or not values <= CANONICAL_DOMAIN_IDS:
            raise ValueError("domínio de leitura desconhecido")
        return values
