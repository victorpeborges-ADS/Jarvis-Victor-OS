"""Wholly local Google Calendar-shaped simulator and SQLite sync service.

This module has no OAuth client and performs no network I/O. Its provider data is
generated in memory and is independent from the repository's DEMO fixture.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from domain_registry import CANONICAL_DOMAIN_IDS
from memory_models import CalendarSyncCheckpoint, EventRecord, ProvenanceRecord, SourceRecord
from memory_store import CalendarCursorConflict, SQLiteMemoryStore

CALENDAR_SOURCE = SourceRecord(
    id="src_calendar_sim_google",
    provider="calendar_sim",
    resource_id="calendar:synthetic-primary",
    scopes=(),
    sync_status="idle",
)
PAGE_SIZE = 2
SYNC_STALE_AFTER = timedelta(hours=24)


class CalendarContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SimulatedCalendar(CalendarContract):
    calendar_id: str = Field(pattern=r"^sim_calendar_[a-h]$")
    name: str = Field(min_length=1, max_length=120)
    time_zone: str = Field(min_length=1, max_length=64)
    provider_mode: Literal["simulated"] = "simulated"

    @field_validator("time_zone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("fuso horário desconhecido") from exc
        return value


class SimulatedCalendarEvent(CalendarContract):
    calendar_id: str = Field(pattern=r"^sim_calendar_[a-h]$")
    event_id: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=500)
    start_at: datetime
    end_at: datetime
    time_zone: str = Field(min_length=1, max_length=64)
    status: Literal["confirmed", "cancelled"] = "confirmed"
    updated_at: datetime

    @field_validator("start_at", "end_at", "updated_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp do evento precisa de fuso horário")
        return value

    @field_validator("time_zone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("fuso horário desconhecido") from exc
        return value

    @model_validator(mode="after")
    def event_range_is_valid(self) -> SimulatedCalendarEvent:
        if self.end_at <= self.start_at:
            raise ValueError("fim do evento precisa ser posterior ao início")
        return self


class CalendarCursor(CalendarContract):
    sync_token: str | None = Field(default=None, max_length=512)
    page_token: str | None = Field(default=None, max_length=512)


class CalendarDeletion(CalendarContract):
    """Typed tombstone for a provider event removed from a calendar."""

    calendar_id: str = Field(pattern=r"^sim_calendar_[a-h]$")
    event_id: str = Field(min_length=1, max_length=256)
    deleted_at: datetime

    @field_validator("deleted_at")
    @classmethod
    def deletion_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp da exclusão precisa de fuso horário")
        return value


class CalendarPage(CalendarContract):
    events: tuple[SimulatedCalendarEvent, ...]
    deletions: tuple[CalendarDeletion, ...] = ()
    next_page_token: str | None = Field(default=None, max_length=512)
    next_sync_token: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def continuation_is_unambiguous(self) -> CalendarPage:
        if (self.next_page_token is None) == (self.next_sync_token is None):
            raise ValueError("página precisa conter exatamente um cursor de continuação")
        deleted_events = {
            event.event_id: event for event in self.events if event.status == "cancelled"
        }
        tombstones = {deletion.event_id: deletion for deletion in self.deletions}
        if set(deleted_events) != set(tombstones):
            raise ValueError("tombstones precisam corresponder aos eventos cancelados da página")
        if any(
            tombstones[event_id].calendar_id != event.calendar_id
            or tombstones[event_id].deleted_at != event.updated_at
            for event_id, event in deleted_events.items()
        ):
            raise ValueError("tombstone diverge do evento cancelado")
        return self


class CalendarProviderError(RuntimeError):
    def __init__(self, code: Literal["simulated_network", "invalid_cursor", "provider_error"], status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class CalendarProvider:
    """In-memory deterministic provider with injectable failures for regression tests."""

    def __init__(self, *, page_size: int = PAGE_SIZE) -> None:
        if page_size < 1 or page_size > 100:
            raise ValueError("tamanho de página fora do limite")
        self.page_size = page_size
        self._lock = threading.RLock()
        self._calendars: dict[str, SimulatedCalendar] = {}
        self._current: dict[str, dict[str, SimulatedCalendarEvent]] = {}
        self._changes: dict[str, list[tuple[int, SimulatedCalendarEvent]]] = {}
        self._revision: dict[str, int] = {}
        self._generation: dict[str, int] = {}
        self._page_sessions: dict[str, tuple[str, tuple[SimulatedCalendarEvent, ...], int, str]] = {}
        self._next_failures: dict[str, CalendarProviderError] = {}
        self._load_synthetic_catalog()

    def _load_synthetic_catalog(self) -> None:
        zone = ZoneInfo("America/Sao_Paulo")
        now = datetime.now(zone).replace(second=0, microsecond=0)
        for index, letter in enumerate("abcdefgh"):
            calendar_id = f"sim_calendar_{letter}"
            self._calendars[calendar_id] = SimulatedCalendar(
                calendar_id=calendar_id,
                name=f"Calendário sintético {letter.upper()}",
                time_zone="America/Sao_Paulo",
            )
            self._current[calendar_id] = {}
            self._changes[calendar_id] = []
            self._revision[calendar_id] = 0
            self._generation[calendar_id] = 1
            for offset in range(2):
                start = now + timedelta(days=index + offset + 1, hours=9 + offset)
                event = SimulatedCalendarEvent(
                    calendar_id=calendar_id,
                    event_id=f"evt-synth-{letter}-{offset + 1}",
                    summary=f"Compromisso sintético {letter.upper()}-{offset + 1}",
                    start_at=start,
                    end_at=start + timedelta(minutes=30),
                    time_zone="America/Sao_Paulo",
                    updated_at=now,
                )
                self.publish_event(event)

    def list_calendars(self) -> tuple[SimulatedCalendar, ...]:
        with self._lock:
            return tuple(self._calendars[key] for key in sorted(self._calendars))

    def get_calendar(self, calendar_id: str) -> SimulatedCalendar | None:
        with self._lock:
            return self._calendars.get(calendar_id)

    def get_event(self, calendar_id: str, event_id: str) -> SimulatedCalendarEvent | None:
        with self._lock:
            return self._current.get(calendar_id, {}).get(event_id)

    def publish_event(self, event_value: SimulatedCalendarEvent | dict) -> SimulatedCalendarEvent:
        event = SimulatedCalendarEvent.model_validate(event_value)
        with self._lock:
            if event.calendar_id not in self._calendars:
                raise ValueError("calendário sintético desconhecido")
            self._revision[event.calendar_id] += 1
            revision = self._revision[event.calendar_id]
            self._current[event.calendar_id][event.event_id] = event
            self._changes[event.calendar_id].append((revision, event))
            return event

    def cancel_event(self, calendar_id: str, event_id: str, *, at: datetime | None = None) -> SimulatedCalendarEvent:
        with self._lock:
            current = self._current.get(calendar_id, {}).get(event_id)
            if current is None:
                raise ValueError("evento sintético ausente")
            cancelled = current.model_copy(update={"status": "cancelled", "updated_at": at or datetime.now(timezone.utc)})
        return self.publish_event(cancelled)

    def fail_next(self, calendar_id: str, *, code: str = "simulated_network") -> None:
        if calendar_id not in self._calendars:
            raise ValueError("calendário sintético desconhecido")
        if code != "simulated_network":
            raise ValueError("falha simulada não suportada")
        with self._lock:
            self._next_failures[calendar_id] = CalendarProviderError("simulated_network", 503)

    def invalidate_cursors(self, calendar_id: str) -> None:
        with self._lock:
            if calendar_id not in self._calendars:
                raise ValueError("calendário sintético desconhecido")
            self._generation[calendar_id] += 1
            self._page_sessions = {
                token: session for token, session in self._page_sessions.items() if session[0] != calendar_id
            }

    def list_events(self, calendar_id: str, cursor: CalendarCursor) -> CalendarPage:
        with self._lock:
            if calendar_id not in self._calendars:
                raise CalendarProviderError("provider_error", 404)
            failure = self._next_failures.pop(calendar_id, None)
            if failure:
                raise failure

            if cursor.page_token is not None:
                session = self._page_sessions.get(cursor.page_token)
                if session is None or session[0] != calendar_id:
                    raise CalendarProviderError("invalid_cursor", 410)
                _calendar_id, events, offset, next_sync_token = session
            else:
                generation = self._generation[calendar_id]
                revision = self._revision[calendar_id]
                if cursor.sync_token is None:
                    events = tuple(self._current[calendar_id][key] for key in sorted(self._current[calendar_id]))
                else:
                    parsed = cursor.sync_token.split(":")
                    if (
                        len(parsed) != 3 or parsed[0] != "sim" or not parsed[1].isdigit()
                        or not parsed[2].isdigit() or int(parsed[1]) != generation
                    ):
                        raise CalendarProviderError("invalid_cursor", 410)
                    last_revision = int(parsed[2])
                    changed = [event for change_revision, event in self._changes[calendar_id] if change_revision > last_revision]
                    latest: dict[str, SimulatedCalendarEvent] = {}
                    for event in changed:
                        latest[event.event_id] = event
                    events = tuple(latest.values())
                offset = 0
                next_sync_token = f"sim:{generation}:{revision}"

            page_events = events[offset:offset + self.page_size]
            deletions = tuple(
                CalendarDeletion(calendar_id=event.calendar_id, event_id=event.event_id, deleted_at=event.updated_at)
                for event in page_events if event.status == "cancelled"
            )
            new_offset = offset + len(page_events)
            if new_offset < len(events):
                page_token = secrets.token_urlsafe(24)
                self._page_sessions[page_token] = (calendar_id, events, new_offset, next_sync_token)
                return CalendarPage(events=page_events, deletions=deletions, next_page_token=page_token)

            if cursor.page_token is not None:
                self._page_sessions.pop(cursor.page_token, None)
            return CalendarPage(events=page_events, deletions=deletions, next_sync_token=next_sync_token)


@dataclass(frozen=True)
class CalendarQuarantine:
    calendar_id: str
    reason: Literal["unclassified", "grant_missing"]


class CalendarSyncState(CalendarContract):
    calendar_id: str
    domain_id: str | None
    provider_mode: Literal["simulated"] = "simulated"
    status: Literal["not_synced", "simulated", "stale", "error"]
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    error_code: Literal["simulated_network", "invalid_cursor", "provider_error"] | None = None

    @field_validator("domain_id")
    @classmethod
    def domain_is_canonical(cls, value: str | None) -> str | None:
        if value is not None and value not in CANONICAL_DOMAIN_IDS:
            raise ValueError("domínio de estado desconhecido")
        return value


class CalendarSyncReport(CalendarContract):
    dataset: Literal["real"] = "real"
    provider_mode: Literal["simulated"] = "simulated"
    events_written: int = Field(default=0, ge=0)
    cancellations_applied: int = Field(default=0, ge=0)
    quarantined: tuple[CalendarQuarantine, ...] = ()
    states: tuple[CalendarSyncState, ...] = ()


class CalendarSyncService:
    def __init__(self, store: SQLiteMemoryStore, provider: CalendarProvider) -> None:
        self.store = store
        self.provider = provider

    def classify(self, calendar_id: str, domain_id: str) -> CalendarSyncCheckpoint:
        if self.provider.get_calendar(calendar_id) is None:
            raise ValueError("calendário sintético desconhecido")
        self.store.ensure_source(CALENDAR_SOURCE)
        return self.store.classify_calendar(
            CALENDAR_SOURCE.id, calendar_id, domain_id, datetime.now(timezone.utc)
        )

    def sync(
        self,
        authorized_domains: frozenset[str],
        calendar_id: str | None = None,
        *,
        is_domain_authorized: Callable[[str], bool] | None = None,
    ) -> CalendarSyncReport:
        if not authorized_domains <= CANONICAL_DOMAIN_IDS:
            raise ValueError("escopo autorizado contém domínio desconhecido")
        calendars = self.provider.list_calendars()
        if calendar_id is not None:
            calendars = tuple(calendar for calendar in calendars if calendar.calendar_id == calendar_id)
            if not calendars:
                raise ValueError("calendário sintético desconhecido")

        self.store.ensure_source(CALENDAR_SOURCE)
        quarantine: list[CalendarQuarantine] = []
        states: list[CalendarSyncState] = []
        written = cancelled = 0
        for calendar in calendars:
            checkpoint = self.store.ensure_calendar_checkpoint(CALENDAR_SOURCE.id, calendar.calendar_id)
            if checkpoint.domain_id is None:
                quarantine.append(CalendarQuarantine(calendar_id=calendar.calendar_id, reason="unclassified"))
                continue
            if checkpoint.domain_id not in authorized_domains:
                quarantine.append(CalendarQuarantine(calendar_id=calendar.calendar_id, reason="grant_missing"))
                continue
            checker = is_domain_authorized or (lambda domain: domain in authorized_domains)
            if not checker(checkpoint.domain_id):
                quarantine.append(CalendarQuarantine(calendar_id=calendar.calendar_id, reason="grant_missing"))
                continue
            try:
                event_count, cancellation_count = self._sync_one(calendar, checker)
            except PermissionError:
                quarantine.append(CalendarQuarantine(calendar_id=calendar.calendar_id, reason="grant_missing"))
                continue
            written += event_count
            cancelled += cancellation_count
            current = self.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, calendar.calendar_id)
            if current is not None:
                states.append(self._state(current))
        return CalendarSyncReport(
            events_written=written,
            cancellations_applied=cancelled,
            quarantined=tuple(quarantine),
            states=tuple(states),
        )

    def _sync_one(
        self,
        calendar: SimulatedCalendar,
        is_domain_authorized: Callable[[str], bool],
    ) -> tuple[int, int]:
        written = cancelled = 0
        for _ in range(1000):
            checkpoint = self.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, calendar.calendar_id)
            if checkpoint is None or checkpoint.domain_id is None:
                raise RuntimeError("classificação do calendário desapareceu")
            if not is_domain_authorized(checkpoint.domain_id):
                raise PermissionError("concessão do calendário foi revogada")
            attempted_at = datetime.now(timezone.utc)
            try:
                page = self.provider.list_events(
                    calendar.calendar_id,
                    CalendarCursor(sync_token=checkpoint.sync_token, page_token=checkpoint.page_token),
                )
            except CalendarProviderError as exc:
                if exc.code == "invalid_cursor":
                    try:
                        self.store.reset_calendar_cursor(
                            checkpoint.source_id, checkpoint.calendar_id, checkpoint.sync_token,
                            checkpoint.page_token, attempted_at,
                        )
                    except CalendarCursorConflict:
                        continue
                    continue
                try:
                    self.store.record_calendar_error(
                        checkpoint.source_id, checkpoint.calendar_id, checkpoint.sync_token,
                        checkpoint.page_token, exc.code, attempted_at,
                    )
                except CalendarCursorConflict:
                    continue
                return written, cancelled

            normalized: list[EventRecord] = []
            cancelled_refs = [
                f"{deletion.calendar_id}:{deletion.event_id}" for deletion in page.deletions
            ]
            observed_at = datetime.now(timezone.utc)
            # A provider may report several revisions of one event in the same
            # incremental window. Only its last state in this page is applied.
            latest_page_events = {item.event_id: item for item in page.events}
            for provider_event in latest_page_events.values():
                external_ref = f"{calendar.calendar_id}:{provider_event.event_id}"
                if provider_event.status == "cancelled":
                    continue
                identity_digest = hashlib.sha256(
                    f"{CALENDAR_SOURCE.dataset}|{CALENDAR_SOURCE.id}|{calendar.calendar_id}|{provider_event.event_id}".encode()
                ).hexdigest()
                normalized.append(EventRecord(
                    id=f"real_evt_cal_{identity_digest}",
                    event_type="appointment",
                    title=provider_event.summary,
                    domain_id=checkpoint.domain_id,
                    sensitivity="normal",
                    occurred_at=provider_event.start_at,
                    payload_minimized={
                        "calendar_id": calendar.calendar_id,
                        "calendar_name": calendar.name,
                        "calendar_time_zone": calendar.time_zone,
                        "event_time_zone": provider_event.time_zone,
                        "end_at": provider_event.end_at.isoformat(),
                        "provider_updated_at": provider_event.updated_at.isoformat(),
                        "provider_status": provider_event.status,
                    },
                    provenance=ProvenanceRecord(
                        source_id=CALENDAR_SOURCE.id,
                        external_ref=external_ref,
                        observed_at=observed_at,
                        last_verified_at=observed_at,
                        classification_method="human_review",
                        classified_at=checkpoint.classified_at,
                    ),
                ))

            if not is_domain_authorized(checkpoint.domain_id):
                raise PermissionError("concessão do calendário foi revogada")

            final = page.next_page_token is None
            try:
                changed = self.store.apply_calendar_page(
                    source_id=checkpoint.source_id,
                    calendar_id=checkpoint.calendar_id,
                    domain_id=checkpoint.domain_id,
                    expected_sync_token=checkpoint.sync_token,
                    expected_page_token=checkpoint.page_token,
                    next_sync_token=page.next_sync_token,
                    next_page_token=page.next_page_token,
                    events=normalized,
                    cancelled_external_refs=cancelled_refs,
                    attempted_at=attempted_at,
                    completed_at=observed_at if final else None,
                )
            except CalendarCursorConflict:
                continue
            # The first number counts event upserts; cancellation updates are also
            # reported by the store's total, so derive each from the page payload.
            written += len(normalized)
            cancelled += min(len(cancelled_refs), max(0, changed - len(normalized)))
            if final:
                return written, cancelled
        raise RuntimeError("sincronização simulada excedeu o limite de páginas")

    @staticmethod
    def _state(checkpoint: CalendarSyncCheckpoint, *, now: datetime | None = None) -> CalendarSyncState:
        instant = now or datetime.now(timezone.utc)
        if checkpoint.sync_status == "error" and (
            checkpoint.last_attempt_at is not None
            and (checkpoint.last_success_at is None or checkpoint.last_attempt_at > checkpoint.last_success_at)
        ):
            status = "error"
        elif checkpoint.last_success_at is None:
            status = "not_synced"
        elif instant - checkpoint.last_success_at >= SYNC_STALE_AFTER:
            status = "stale"
        else:
            status = "simulated"
        return CalendarSyncState(
            calendar_id=checkpoint.calendar_id,
            domain_id=checkpoint.domain_id,
            status=status,
            last_success_at=checkpoint.last_success_at,
            last_attempt_at=checkpoint.last_attempt_at,
            error_code=checkpoint.error_code if status == "error" else None,
        )

    def states(self) -> tuple[CalendarSyncState, ...]:
        output = []
        for calendar in self.provider.list_calendars():
            checkpoint = self.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, calendar.calendar_id)
            if checkpoint is None:
                checkpoint = CalendarSyncCheckpoint(
                    source_id=CALENDAR_SOURCE.id,
                    calendar_id=calendar.calendar_id,
                )
            output.append(self._state(checkpoint))
        return tuple(output)
