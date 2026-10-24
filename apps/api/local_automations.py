"""Persistent, local-only schedules. The worker exists only with the native app."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import unicodedata
from datetime import datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from local_captures import DOMAIN_ID, list_captures
from memory_store import SQLiteMemoryStore
from mission_repository import MissionRepository

WORKFLOW_VERSIONS = {
    "reminder": "reminder.v1",
    "morning_briefing": "morning-briefing.v1",
    "idea_mission_review": "idea-mission-review.v1",
}
AUTOMATION_KINDS = frozenset(WORKFLOW_VERSIONS)
MAX_AUTOMATIONS = 3
MAX_RETRIES = 2
POLL_INTERVAL_SECONDS = 15
LATE_GRACE = timedelta(minutes=2)
MAX_TITLE = 24
MAX_MESSAGE = 32
_HHMM = re.compile(r"\A(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_LOCAL_DATETIME = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_ID = re.compile(r"\A[0-9a-f]{32}\Z")
UTC = timezone.utc


class AutomationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _has_control(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise AutomationError("scope_invalid")
    return now.astimezone(UTC)


def _iso(now: datetime) -> str:
    return _utc(now).isoformat(timespec="microseconds")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AutomationError("operation_failed")
    return parsed.astimezone(UTC)


def _parse_time(value: str | None) -> time | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or _HHMM.fullmatch(value) is None:
        raise AutomationError("automation_invalid")
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def _zone(value: str) -> ZoneInfo:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or value.startswith("/") or ".." in value:
        raise AutomationError("automation_invalid")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise AutomationError("automation_invalid") from None


def _wall_candidates(wall: datetime, zone: ZoneInfo) -> list[datetime]:
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold)
        instant = candidate.astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == wall:
            candidates[instant] = candidate
    return [candidates[key] for key in sorted(candidates)]


def resolve_wall_time(wall: datetime, zone: ZoneInfo) -> datetime:
    """Use the first instant for an ambiguous time and move a DST gap forward."""
    if wall.tzinfo is not None:
        raise AutomationError("automation_invalid")
    # IANA zones include historical date-line jumps as large as 24 hours,
    # in addition to ordinary one-hour DST gaps.
    for shift in range(24 * 60 + 1):
        adjusted = wall + timedelta(minutes=shift)
        candidates = _wall_candidates(adjusted, zone)
        if candidates:
            return candidates[0].astimezone(UTC)
    raise AutomationError("automation_invalid")


def next_run_at(recurrence: str, local_schedule: str, timezone_name: str, after: datetime) -> datetime:
    after_utc = _utc(after)
    zone = _zone(timezone_name)
    if recurrence == "once":
        if not isinstance(local_schedule, str) or _LOCAL_DATETIME.fullmatch(local_schedule) is None:
            raise AutomationError("automation_invalid")
        try:
            wall = datetime.strptime(local_schedule, "%Y-%m-%dT%H:%M")
        except ValueError:
            raise AutomationError("automation_invalid") from None
        return resolve_wall_time(wall, zone)
    if recurrence != "daily" or _HHMM.fullmatch(local_schedule) is None:
        raise AutomationError("automation_invalid")
    hour, minute = (int(part) for part in local_schedule.split(":"))
    local_after = after_utc.astimezone(zone)
    for offset in range(0, 9):
        target_date = local_after.date() + timedelta(days=offset)
        candidate = resolve_wall_time(datetime.combine(target_date, time(hour, minute)), zone)
        if candidate > after_utc:
            return candidate
    raise AutomationError("automation_invalid")


def _quiet_end(due: datetime, timezone_name: str, quiet_start: str | None, quiet_end: str | None) -> datetime | None:
    start = _parse_time(quiet_start)
    end = _parse_time(quiet_end)
    if start is None and end is None:
        return None
    if start is None or end is None or start == end:
        raise AutomationError("automation_invalid")
    zone = _zone(timezone_name)
    local = _utc(due).astimezone(zone)
    local_time = local.timetz().replace(tzinfo=None)
    if start < end:
        active = start <= local_time < end
        end_date = local.date()
    else:
        active = local_time >= start or local_time < end
        end_date = local.date() + (timedelta(days=1) if local_time >= start else timedelta())
    if not active:
        return None
    return resolve_wall_time(datetime.combine(end_date, end), zone)


def _sources_for(kind: str) -> list[str]:
    if kind == "reminder":
        return ["user-authored-reminder"]
    if kind in {"morning_briefing", "idea_mission_review"}:
        return ["local_captures", "missions:dom_synthetic_a"]
    raise AutomationError("scope_invalid")


def _row_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["sources"] = json.loads(item.pop("sources_json"))
    return item


def create_automation(
    store: SQLiteMemoryStore,
    *,
    owner: str,
    kind: str,
    title: str,
    recurrence: str,
    local_schedule: str,
    timezone_name: str,
    message: str = "",
    quiet_start: str | None = None,
    quiet_end: str | None = None,
    now: datetime,
) -> dict:
    instant = _utc(now)
    if owner != "owner" or kind not in AUTOMATION_KINDS or recurrence not in {"once", "daily"}:
        raise AutomationError("scope_invalid")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= MAX_TITLE or _has_control(title):
        raise AutomationError("automation_invalid")
    title = title.strip()
    if kind == "reminder":
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= MAX_MESSAGE or _has_control(message):
            raise AutomationError("automation_invalid")
        message = message.strip()
    elif message:
        raise AutomationError("automation_invalid")
    _quiet_end(instant, timezone_name, quiet_start, quiet_end)
    next_at = next_run_at(recurrence, local_schedule, timezone_name, instant)
    if next_at <= instant:
        raise AutomationError("automation_invalid")
    source_json = json.dumps(_sources_for(kind), ensure_ascii=True, separators=(",", ":"))
    automation_id = secrets.token_hex(16)
    timestamp = _iso(instant)
    with store.transaction() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM local_automations WHERE owner=? AND state != 'deleted'",
            (owner,),
        ).fetchone()[0]
        if count >= MAX_AUTOMATIONS:
            raise AutomationError("automation_limit")
        connection.execute(
            """INSERT INTO local_automations (
                id, owner, kind, title, recurrence, local_schedule, timezone,
                quiet_start, quiet_end, message, sources_json, workflow_version,
                state, next_run_at_utc, max_retries, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
            (
                automation_id, owner, kind, title, recurrence, local_schedule, timezone_name,
                quiet_start or None, quiet_end or None, message, source_json,
                WORKFLOW_VERSIONS[kind], _iso(next_at), MAX_RETRIES, timestamp, timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM local_automations WHERE id=?", (automation_id,)).fetchone()
    return _row_dict(row)


def list_automations(store: SQLiteMemoryStore, owner: str = "owner") -> list[dict]:
    if owner != "owner":
        raise AutomationError("session_required")
    with store.transaction() as connection:
        rows = connection.execute(
            "SELECT * FROM local_automations WHERE owner=? AND state != 'deleted' ORDER BY created_at DESC, id DESC LIMIT ?",
            (owner, MAX_AUTOMATIONS),
        ).fetchall()
    return [_row_dict(row) for row in rows]


def get_automation(store: SQLiteMemoryStore, owner: str, automation_id: str) -> dict:
    if owner != "owner" or _ID.fullmatch(automation_id or "") is None:
        raise AutomationError("scope_invalid")
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM local_automations WHERE id=? AND owner=?",
            (automation_id, owner),
        ).fetchone()
    if row is None:
        raise AutomationError("automation_not_found")
    return _row_dict(row)


def list_runs(store: SQLiteMemoryStore, owner: str, automation_id: str, limit: int = 5) -> list[dict]:
    if owner != "owner" or _ID.fullmatch(automation_id or "") is None:
        raise AutomationError("scope_invalid")
    with store.transaction() as connection:
        exists = connection.execute(
            "SELECT 1 FROM local_automations WHERE id=? AND owner=?",
            (automation_id, owner),
        ).fetchone()
        if exists is None:
            raise AutomationError("automation_not_found")
        rows = connection.execute(
            """SELECT id, scheduled_for_utc, workflow_version, status, attempts,
                      next_attempt_at_utc, error_code, source_refs_json, created_at, completed_at
               FROM local_automation_runs WHERE automation_id=?
               ORDER BY scheduled_for_utc DESC, created_at DESC LIMIT ?""",
            (automation_id, min(max(limit, 1), 5)),
        ).fetchall()
    return [{**dict(row), "sources": json.loads(row["source_refs_json"])} for row in rows]


def get_run(store: SQLiteMemoryStore, owner: str, automation_id: str, run_id: str) -> dict:
    if owner != "owner" or _ID.fullmatch(automation_id or "") is None or _ID.fullmatch(run_id or "") is None:
        raise AutomationError("scope_invalid")
    with store.transaction() as connection:
        row = connection.execute(
            """SELECT id, automation_id, scheduled_for_utc, workflow_version, status,
                      attempts, result_text, source_refs_json, error_code, created_at, completed_at
               FROM local_automation_runs WHERE id=? AND automation_id=?""",
            (run_id, automation_id),
        ).fetchone()
    if row is None:
        raise AutomationError("automation_not_found")
    item = dict(row)
    item["sources"] = json.loads(item.pop("source_refs_json"))
    return item


def update_timezone(store: SQLiteMemoryStore, owner: str, automation_id: str, timezone_name: str, now: datetime) -> dict:
    if owner != "owner" or _ID.fullmatch(automation_id or "") is None:
        raise AutomationError("scope_invalid")
    instant = _utc(now)
    _zone(timezone_name)
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM local_automations WHERE id=? AND owner=?",
            (automation_id, owner),
        ).fetchone()
        if row is None:
            raise AutomationError("automation_not_found")
        if row["state"] in {"deleted", "completed"}:
            raise AutomationError("automation_conflict")
        _supersede_unstarted_runs(connection, automation_id, instant, "timezone_changed")
        next_at = None if row["state"] == "paused" else next_run_at(
            row["recurrence"], row["local_schedule"], timezone_name, instant
        )
        if next_at is not None and next_at <= instant:
            raise AutomationError("automation_invalid")
        connection.execute(
            "UPDATE local_automations SET timezone=?, next_run_at_utc=?, updated_at=? WHERE id=?",
            (timezone_name, _iso(next_at) if next_at else None, _iso(instant), automation_id),
        )
        updated = connection.execute("SELECT * FROM local_automations WHERE id=?", (automation_id,)).fetchone()
    return _row_dict(updated)


def _advance(connection: sqlite3.Connection, automation: sqlite3.Row, after: datetime) -> None:
    if automation["recurrence"] == "once":
        connection.execute(
            "UPDATE local_automations SET state='completed', next_run_at_utc=NULL, updated_at=? WHERE id=?",
            (_iso(after), automation["id"]),
        )
        return
    upcoming = next_run_at("daily", automation["local_schedule"], automation["timezone"], after)
    connection.execute(
        "UPDATE local_automations SET next_run_at_utc=?, updated_at=? WHERE id=?",
        (_iso(upcoming), _iso(after), automation["id"]),
    )


def _supersede_unstarted_runs(
    connection: sqlite3.Connection,
    automation_id: str,
    instant: datetime,
    reason: str,
) -> None:
    """Keep queued occurrences in history without executing an obsolete schedule."""
    timestamp = _iso(instant)
    connection.execute(
        """UPDATE local_automation_runs
           SET status='superseded', error_code=?, next_attempt_at_utc=NULL,
               completed_at=?, updated_at=?
           WHERE automation_id=? AND status IN ('pending', 'deferred', 'retry_wait')""",
        (reason, timestamp, timestamp, automation_id),
    )


def control_automation(
    store: SQLiteMemoryStore,
    *,
    owner: str,
    automation_id: str,
    action: str,
    now: datetime,
    run_id: str | None = None,
) -> dict:
    instant = _utc(now)
    if owner != "owner" or _ID.fullmatch(automation_id or "") is None:
        raise AutomationError("scope_invalid")
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM local_automations WHERE id=? AND owner=?",
            (automation_id, owner),
        ).fetchone()
        if row is None:
            raise AutomationError("automation_not_found")
        if action == "pause" and row["state"] == "active":
            _supersede_unstarted_runs(connection, automation_id, instant, "schedule_paused")
            connection.execute(
                "UPDATE local_automations SET state='paused', next_run_at_utc=NULL, updated_at=? WHERE id=?",
                (_iso(instant), automation_id),
            )
        elif action == "resume" and row["state"] == "paused":
            _supersede_unstarted_runs(connection, automation_id, instant, "schedule_resumed")
            next_at = next_run_at(row["recurrence"], row["local_schedule"], row["timezone"], instant)
            if next_at <= instant:
                raise AutomationError("automation_invalid")
            connection.execute(
                "UPDATE local_automations SET state='active', next_run_at_utc=?, updated_at=? WHERE id=?",
                (_iso(next_at), _iso(instant), automation_id),
            )
        elif action == "delete" and row["state"] != "deleted":
            _supersede_unstarted_runs(connection, automation_id, instant, "schedule_deleted")
            connection.execute(
                "UPDATE local_automations SET state='deleted', next_run_at_utc=NULL, updated_at=? WHERE id=?",
                (_iso(instant), automation_id),
            )
        elif action in {"recover", "retry"}:
            if _ID.fullmatch(run_id or "") is None:
                raise AutomationError("scope_invalid")
            expected = "missed" if action == "recover" else "failed"
            run = connection.execute(
                "SELECT id, attempts FROM local_automation_runs WHERE id=? AND automation_id=? AND status=?",
                (run_id, automation_id, expected),
            ).fetchone()
            if run is not None and run["attempts"] >= 3:
                raise AutomationError("automation_conflict")
            recover_completed_once = (
                run is not None and row["state"] == "completed" and row["recurrence"] == "once"
            )
            updated = connection.execute(
                """UPDATE local_automation_runs SET status='pending', next_attempt_at_utc=?,
                          error_code=NULL, updated_at=?
                   WHERE id=? AND automation_id=? AND status=?""",
                (_iso(instant), _iso(instant), run_id, automation_id, expected),
            )
            if updated.rowcount != 1 or (row["state"] != "active" and not recover_completed_once):
                raise AutomationError("automation_conflict")
            if recover_completed_once:
                connection.execute(
                    "UPDATE local_automations SET state='active', updated_at=? WHERE id=?",
                    (_iso(instant), automation_id),
                )
        else:
            raise AutomationError("automation_conflict")
        result = connection.execute("SELECT * FROM local_automations WHERE id=?", (automation_id,)).fetchone()
    return _row_dict(result)


class LocalAutomationScheduler:
    """Clock-injected worker; no thread or task is created by this class."""

    def __init__(self, store: SQLiteMemoryStore, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self._session_lock = threading.RLock()
        self._session_token: str | None = None

    def set_session(self, token: str) -> None:
        with self._session_lock:
            self._session_token = token

    def clear_session(self, token: str | None = None) -> None:
        with self._session_lock:
            if token is None or self._session_token == token:
                self._session_token = None

    def startup_reconcile(self, now: datetime | None = None) -> int:
        instant = _utc(now or self.clock())
        timestamp = _iso(instant)
        missed_count = 0
        with self.store.transaction() as connection:
            interrupted = connection.execute(
                """SELECT r.id AS run_id, r.automation_id AS run_automation_id, a.*
                   FROM local_automation_runs r
                   JOIN local_automations a ON a.id=r.automation_id
                   WHERE r.status IN ('running', 'deferred', 'retry_wait')
                     AND a.state='active'
                     AND COALESCE(r.next_attempt_at_utc, a.next_run_at_utc) <= ?""",
                (timestamp,),
            ).fetchall()
            for run in interrupted:
                connection.execute(
                    """UPDATE local_automation_runs SET status='missed', error_code='app_inactive',
                              completed_at=?, updated_at=? WHERE id=?""",
                    (timestamp, timestamp, run["run_id"]),
                )
                automation = connection.execute(
                    "SELECT * FROM local_automations WHERE id=?", (run["run_automation_id"],)
                ).fetchone()
                if automation and automation["state"] == "active":
                    _advance(connection, automation, instant)
                missed_count += 1

            due = connection.execute(
                "SELECT * FROM local_automations WHERE state='active' AND next_run_at_utc < ?",
                (timestamp,),
            ).fetchall()
            for automation in due:
                scheduled = automation["next_run_at_utc"]
                exists = connection.execute(
                    "SELECT id, status, next_attempt_at_utc FROM local_automation_runs WHERE automation_id=? AND scheduled_for_utc=?",
                    (automation["id"], scheduled),
                ).fetchone()
                # A persisted retry is still live until its own retry time. In
                # particular, do not complete a one-time schedule just because
                # its original occurrence is now in the past.
                if (
                    exists is not None
                    and exists["status"] in {"retry_wait", "deferred"}
                    and exists["next_attempt_at_utc"] is not None
                    and exists["next_attempt_at_utc"] > timestamp
                ):
                    continue
                if exists is None:
                    run_id = hashlib.sha256(f"{automation['id']}|{scheduled}".encode()).hexdigest()[:32]
                    connection.execute(
                        """INSERT INTO local_automation_runs (
                            id, automation_id, scheduled_for_utc, idempotency_key, workflow_version,
                            status, attempts, error_code, created_at, completed_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'missed', 0, 'app_inactive', ?, ?, ?)""",
                        (run_id, automation["id"], scheduled, f"{automation['id']}:{scheduled}",
                         automation["workflow_version"], timestamp, timestamp, timestamp),
                    )
                    missed_count += 1
                elif exists["status"] not in {"missed", "retry_wait"}:
                    connection.execute(
                        "UPDATE local_automation_runs SET status='missed', error_code='app_inactive', completed_at=?, updated_at=? WHERE id=?",
                        (timestamp, timestamp, exists["id"]),
                    )
                    missed_count += 1
                _advance(connection, automation, instant)
        return missed_count

    def run_due(self, now: datetime | None = None) -> int:
        instant = _utc(now or self.clock())
        timestamp = _iso(instant)
        with self.store.transaction() as connection:
            rows = connection.execute(
                """SELECT * FROM local_automation_runs
                   WHERE status IN ('pending', 'retry_wait', 'deferred')
                     AND COALESCE(next_attempt_at_utc, scheduled_for_utc) <= ?
                   ORDER BY scheduled_for_utc, id LIMIT 10""",
                (timestamp,),
            ).fetchall()
        processed = 0
        for run in rows:
            scheduled_attempt = _parse_iso(run["next_attempt_at_utc"] or run["scheduled_for_utc"])
            if instant - scheduled_attempt > LATE_GRACE:
                if self._mark_late_run_missed(run["id"], instant):
                    processed += 1
                continue
            if self._claim_and_execute(run["id"], instant):
                processed += 1

        with self.store.transaction() as connection:
            schedules = connection.execute(
                "SELECT * FROM local_automations WHERE state='active' AND next_run_at_utc <= ? ORDER BY next_run_at_utc LIMIT ?",
                (timestamp, MAX_AUTOMATIONS),
            ).fetchall()
        for automation in schedules:
            scheduled = automation["next_run_at_utc"]
            with self.store.transaction() as connection:
                current = connection.execute(
                    "SELECT * FROM local_automations WHERE id=? AND state='active'",
                    (automation["id"],),
                ).fetchone()
                if current is None or current["next_run_at_utc"] != scheduled:
                    continue
                existing = connection.execute(
                    "SELECT id, status FROM local_automation_runs WHERE automation_id=? AND scheduled_for_utc=?",
                    (current["id"], scheduled),
                ).fetchone()
                if existing is not None:
                    continue
                scheduled_at = _parse_iso(scheduled)
                if instant - scheduled_at > LATE_GRACE:
                    run_id = hashlib.sha256(f"{current['id']}|{scheduled}".encode()).hexdigest()[:32]
                    connection.execute(
                        """INSERT INTO local_automation_runs (
                            id, automation_id, scheduled_for_utc, idempotency_key, workflow_version,
                            status, attempts, error_code, created_at, completed_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'missed', 0, 'late_run', ?, ?, ?)""",
                        (run_id, current["id"], scheduled, f"{current['id']}:{scheduled}",
                         current["workflow_version"], timestamp, timestamp, timestamp),
                    )
                    _advance(connection, current, instant)
                    processed += 1
                    continue
                run_id = hashlib.sha256(f"{current['id']}|{scheduled}".encode()).hexdigest()[:32]
                connection.execute(
                    """INSERT OR IGNORE INTO local_automation_runs (
                        id, automation_id, scheduled_for_utc, idempotency_key, workflow_version,
                        status, attempts, next_attempt_at_utc, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
                    (run_id, current["id"], scheduled, f"{current['id']}:{scheduled}",
                     current["workflow_version"], scheduled, timestamp, timestamp),
                )
            if self._claim_and_execute(run_id, instant):
                processed += 1
        return processed

    def _mark_late_run_missed(self, run_id: str, instant: datetime) -> bool:
        timestamp = _iso(instant)
        with self.store.transaction() as connection:
            run = connection.execute(
                "SELECT automation_id FROM local_automation_runs WHERE id=? AND status IN ('pending', 'retry_wait', 'deferred')",
                (run_id,),
            ).fetchone()
            if run is None:
                return False
            updated = connection.execute(
                """UPDATE local_automation_runs SET status='missed', error_code='late_run',
                          completed_at=?, updated_at=?
                   WHERE id=? AND status IN ('pending', 'retry_wait', 'deferred')""",
                (timestamp, timestamp, run_id),
            )
            if updated.rowcount != 1:
                return False
            automation = connection.execute(
                "SELECT * FROM local_automations WHERE id=? AND state='active'",
                (run["automation_id"],),
            ).fetchone()
            if automation is not None:
                _advance(connection, automation, instant)
        return True

    def _claim_and_execute(self, run_id: str, instant: datetime) -> bool:
        timestamp = _iso(instant)
        with self.store.transaction() as connection:
            run = connection.execute(
                "SELECT * FROM local_automation_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None or run["status"] not in {"pending", "retry_wait", "deferred"}:
                return False
            if run["next_attempt_at_utc"] and run["next_attempt_at_utc"] > timestamp:
                return False
            automation = connection.execute(
                "SELECT * FROM local_automations WHERE id=? AND state='active'",
                (run["automation_id"],),
            ).fetchone()
            if automation is None:
                return False
            deferred_until = _quiet_end(
                instant, automation["timezone"], automation["quiet_start"], automation["quiet_end"]
            )
            if deferred_until is not None:
                connection.execute(
                    """UPDATE local_automation_runs SET status='deferred', next_attempt_at_utc=?,
                              updated_at=? WHERE id=?""",
                    (_iso(deferred_until), timestamp, run_id),
                )
                connection.execute(
                    "UPDATE local_automations SET next_run_at_utc=?, updated_at=? WHERE id=?",
                    (_iso(deferred_until), timestamp, automation["id"]),
                )
                return False
            attempts = run["attempts"] + 1
            connection.execute(
                """UPDATE local_automation_runs SET status='running', attempts=?, started_at=?,
                          next_attempt_at_utc=NULL, updated_at=? WHERE id=?""",
                (attempts, timestamp, timestamp, run_id),
            )
            automation = dict(automation)
        try:
            result_text, source_refs = self._build_result(automation, instant)
        except AutomationError as exc:
            self._record_failure(run_id, automation, instant, attempts, exc.code, retryable=False)
            return True
        except sqlite3.OperationalError:
            self._record_failure(run_id, automation, instant, attempts, "storage_temporary", retryable=True)
            return True
        except (OSError, sqlite3.DatabaseError):
            self._record_failure(run_id, automation, instant, attempts, "storage_failure", retryable=False)
            return True
        except Exception:
            self._record_failure(run_id, automation, instant, attempts, "workflow_failure", retryable=False)
            return True
        timestamp = _iso(instant)
        with self.store.transaction() as connection:
            current_run = connection.execute(
                "SELECT status FROM local_automation_runs WHERE id=?", (run_id,)
            ).fetchone()
            if current_run is None or current_run["status"] != "running":
                return False
            connection.execute(
                """UPDATE local_automation_runs SET status='succeeded', result_text=?, source_refs_json=?,
                          error_code=NULL, completed_at=?, updated_at=? WHERE id=?""",
                (result_text, json.dumps(source_refs, ensure_ascii=True, separators=(",", ":")),
                 timestamp, timestamp, run_id),
            )
            current_automation = connection.execute(
                "SELECT * FROM local_automations WHERE id=?", (automation["id"],)
            ).fetchone()
            if current_automation is not None and current_automation["state"] == "active":
                _advance(connection, current_automation, instant)
        return True

    def _record_failure(
        self,
        run_id: str,
        automation: dict,
        instant: datetime,
        attempts: int,
        code: str,
        *,
        retryable: bool,
    ) -> None:
        timestamp = _iso(instant)
        retry = retryable and attempts <= automation["max_retries"]
        next_attempt = instant + timedelta(seconds=15 * (2 ** max(0, attempts - 1))) if retry else None
        with self.store.transaction() as connection:
            connection.execute(
                """UPDATE local_automation_runs SET status=?, error_code=?, next_attempt_at_utc=?,
                          completed_at=?, updated_at=? WHERE id=? AND status='running'""",
                ("retry_wait" if retry else "failed", code,
                 _iso(next_attempt) if next_attempt else None,
                 None if retry else timestamp, timestamp, run_id),
            )
            if not retry:
                current = connection.execute(
                    "SELECT * FROM local_automations WHERE id=? AND state='active'",
                    (automation["id"],),
                ).fetchone()
                if current is not None:
                    _advance(connection, current, instant)

    def recover(self, run_id: str, now: datetime | None = None) -> bool:
        instant = _utc(now or self.clock())
        with self.store.transaction() as connection:
            run = connection.execute(
                "SELECT automation_id FROM local_automation_runs WHERE id=? AND status='pending'",
                (run_id,),
            ).fetchone()
            if run is None:
                return False
        return self._claim_and_execute(run_id, instant)

    def _build_result(self, automation: dict, now: datetime) -> tuple[str, list[dict]]:
        kind = automation["kind"]
        if kind == "reminder":
            return automation["message"], [{"source": "user-authored-reminder", "id": automation["id"], "observed_at": automation["created_at"]}]

        with self._session_lock:
            token = self._session_token
        if not token:
            raise AutomationError("authorization_required")
        from local_security import _native_session, mission_read_confirmed

        try:
            session = _native_session(token)
        except Exception:
            self.clear_session(token)
            raise AutomationError("authorization_required") from None
        try:
            with mission_read_confirmed(session.principal, DOMAIN_ID, session.token):
                captures = list_captures(self.store, session.principal)[:2]
                page = MissionRepository(self.store).list_page(
                    session.principal, DOMAIN_ID, 2, None, frozenset({DOMAIN_ID})
                )
        except PermissionError:
            raise AutomationError("authorization_required") from None
        if page["corrupt"]:
            raise AutomationError("source_unavailable")
        missions = page["items"][:3]
        pieces = []
        if captures:
            pieces.append("Ideias: " + "; ".join(item["text"] for item in captures))
        if missions:
            pieces.append("Missões: " + "; ".join(
                f"{item['mission']['title']} ({item['mission']['status']})" for item in missions
            ))
        if not pieces:
            pieces.append("Nenhuma ideia ou missão local encontrada.")
        prefix = "Briefing da manhã" if kind == "morning_briefing" else "Revisão local de ideias e missões"
        output = f"{prefix}: " + " · ".join(pieces)
        output = output[:1000]
        sources = [
            {"source": "local_captures", "id": item["id"], "observed_at": item["created_at"]}
            for item in captures
        ] + [
            {"source": "missions:dom_synthetic_a", "id": item["mission"]["id"], "observed_at": item["updated_at"]}
            for item in missions
        ]
        if not sources:
            sources = [{"source": "local-empty-state", "id": "dom_synthetic_a", "observed_at": _iso(now)}]
        return output, sources


async def run_app_worker(scheduler: LocalAutomationScheduler) -> None:
    """Run only while the supervised FastAPI application lifespan is active."""
    import asyncio

    scheduler.startup_reconcile()
    while True:
        scheduler.run_due()
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
