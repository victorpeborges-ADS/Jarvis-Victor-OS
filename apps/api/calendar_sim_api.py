"""Authenticated HTTP surface for the local-only Calendar simulator."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain_registry import CANONICAL_DOMAIN_IDS
from local_security import _session_from, authorized_calendar_domains
from calendar_simulator import (
    CalendarSyncReport,
    CalendarSyncService,
    CalendarSyncState,
    SimulatedCalendar,
)

router = APIRouter(prefix="/real/calendar-sim", tags=["calendar-simulated"])


class ClassificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: str

    @field_validator("domain_id")
    @classmethod
    def known_domain(cls, value: str) -> str:
        if value not in CANONICAL_DOMAIN_IDS:
            raise ValueError("domínio desconhecido")
        return value


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendar_id: str | None = Field(default=None, pattern=r"^sim_calendar_[a-h]$")


class CalendarMappingOut(BaseModel):
    calendar_id: str
    domain_id: str
    classified_at: datetime
    provider_mode: Literal["simulated"] = "simulated"


class CalendarCatalogOut(BaseModel):
    provider_mode: Literal["simulated"] = "simulated"
    calendars: tuple[SimulatedCalendar, ...]


class CalendarStatesOut(BaseModel):
    provider_mode: Literal["simulated"] = "simulated"
    states: tuple[CalendarSyncState, ...]


def _service(request: Request) -> CalendarSyncService:
    return request.app.state.calendar_sync_service


@router.get("/calendars", response_model=CalendarCatalogOut)
def list_simulated_calendars(request: Request) -> CalendarCatalogOut:
    _session_from(request)
    return CalendarCatalogOut(calendars=_service(request).provider.list_calendars())


@router.put("/calendars/{calendar_id}/classification", response_model=CalendarMappingOut)
def classify_simulated_calendar(
    calendar_id: str, body: ClassificationIn, request: Request
) -> CalendarMappingOut:
    session = _session_from(request, mutation=True)
    if body.domain_id not in authorized_calendar_domains(session.principal):
        raise HTTPException(status_code=403, detail="concessão de leitura para o domínio ausente")
    try:
        checkpoint = _service(request).classify(calendar_id, body.domain_id)
    except ValueError as exc:
        status_code = 404 if "desconhecido" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    assert checkpoint.domain_id is not None and checkpoint.classified_at is not None
    return CalendarMappingOut(
        calendar_id=checkpoint.calendar_id,
        domain_id=checkpoint.domain_id,
        classified_at=checkpoint.classified_at,
    )


@router.post("/sync", response_model=CalendarSyncReport)
def synchronize_simulated_calendars(body: SyncIn, request: Request) -> CalendarSyncReport:
    session = _session_from(request, mutation=True)
    domains = authorized_calendar_domains(session.principal)
    if not domains:
        raise HTTPException(status_code=403, detail="concessão de leitura para Calendar simulado ausente")
    try:
        return _service(request).sync(
            domains,
            body.calendar_id,
            is_domain_authorized=lambda domain: domain in authorized_calendar_domains(session.principal),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/state", response_model=CalendarStatesOut)
def simulated_sync_state(request: Request) -> CalendarStatesOut:
    session = _session_from(request)
    domains = authorized_calendar_domains(session.principal)
    visible = tuple(
        state for state in _service(request).states()
        if state.domain_id is not None and state.domain_id in domains
    )
    return CalendarStatesOut(states=visible)
