"""Authenticated HTTP surface for the local-only Calendar simulator."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain_registry import CANONICAL_DOMAIN_IDS
from local_security import (
    _session_from,
    authorized_calendar_domains,
    authorized_calendar_inventory_domains,
    calendar_grant_guard,
)
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
    session = _session_from(request)
    domains = authorized_calendar_domains(session.principal)
    if not domains:
        raise HTTPException(status_code=403, detail="concessão de leitura para o catálogo Calendar ausente")
    service = _service(request)
    try:
        # Discovery of unclassified names requires the limited inventory grant.
        # Classified calendars stay inside the event-read domains.
        with calendar_grant_guard(session.principal, domains):
            inventory = authorized_calendar_inventory_domains(session.principal)
            domain_by_calendar = {state.calendar_id: state.domain_id for state in service.states()}
            visible = []
            for calendar in service.provider.list_calendars():
                domain_id = domain_by_calendar.get(calendar.calendar_id)
                if domain_id is None:
                    if inventory:
                        visible.append(calendar)
                elif domain_id in domains:
                    visible.append(calendar)
            return CalendarCatalogOut(calendars=tuple(visible))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão revogada durante a leitura do catálogo") from exc


@router.put("/calendars/{calendar_id}/classification", response_model=CalendarMappingOut)
def classify_simulated_calendar(
    calendar_id: str, body: ClassificationIn, request: Request
) -> CalendarMappingOut:
    session = _session_from(request, mutation=True)
    if body.domain_id not in authorized_calendar_domains(session.principal):
        raise HTTPException(status_code=403, detail="concessão de leitura para o domínio ausente")
    service = _service(request)
    if service.provider.get_calendar(calendar_id) is None:
        raise HTTPException(status_code=404, detail="calendário sintético desconhecido")
    current = next((state.domain_id for state in service.states() if state.calendar_id == calendar_id), None)
    if current is None and body.domain_id not in authorized_calendar_inventory_domains(session.principal):
        raise HTTPException(status_code=403, detail="inventário limitado ausente para calendário não classificado")
    if current is not None and current not in authorized_calendar_domains(session.principal):
        raise HTTPException(status_code=403, detail="concessão de leitura para o domínio ausente")
    try:
        with calendar_grant_guard(session.principal, frozenset({body.domain_id})):
            checkpoint = service.classify(calendar_id, body.domain_id)
    except ValueError as exc:
        status_code = 404 if "desconhecido" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão de leitura para o domínio ausente") from exc
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
        report = _service(request).sync(
            domains,
            body.calendar_id,
            is_domain_authorized=lambda domain: domain in authorized_calendar_domains(session.principal),
            authorization_guard=lambda domain: calendar_grant_guard(
                session.principal, frozenset({domain})
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        # The report aggregates the request's initial authorized scope. Recheck
        # that entire scope under the revocation lock before returning any
        # counts or domain state; a later revocation may still race with delivery.
        with calendar_grant_guard(session.principal, domains):
            return report
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão revogada durante a sincronização") from exc


@router.get("/state", response_model=CalendarStatesOut)
def simulated_sync_state(request: Request) -> CalendarStatesOut:
    session = _session_from(request)
    domains = authorized_calendar_domains(session.principal)
    if not domains:
        raise HTTPException(status_code=403, detail="concessão de leitura para Calendar simulado ausente")
    visible = tuple(
        state for state in _service(request).states()
        if state.domain_id is not None and state.domain_id in domains
    )
    visible_domains = frozenset(state.domain_id for state in visible if state.domain_id is not None)
    try:
        with calendar_grant_guard(session.principal, visible_domains):
            return CalendarStatesOut(states=visible)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="concessão revogada") from exc
