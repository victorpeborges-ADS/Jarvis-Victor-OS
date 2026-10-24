from __future__ import annotations

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from shutil import copyfile
from zoneinfo import ZoneInfo

import pytest

from local_automations import (
    AutomationError,
    LocalAutomationScheduler,
    control_automation,
    create_automation,
    get_automation,
    get_run,
    list_runs,
    next_run_at,
    resolve_wall_time,
    update_timezone,
)
from memory_store import MIGRATIONS_DIR, SQLiteMemoryStore

UTC = timezone.utc


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def store(tmp_path, encrypted_store_factory):
    result = encrypted_store_factory(tmp_path / "private" / "memory.sqlite3")
    result.initialize()
    return result


def make_reminder(store, *, now=None, recurrence="daily", local_schedule="08:00", timezone_name="UTC", **kwargs):
    return create_automation(
        store,
        owner="owner",
        kind="reminder",
        title="Lembrete local",
        recurrence=recurrence,
        local_schedule=local_schedule,
        timezone_name=timezone_name,
        message="Revisar a ideia sintética",
        now=now or instant("2026-10-12T07:00:00Z"),
        **kwargs,
    )


def test_dst_gap_moves_forward_and_overlap_uses_first_occurrence():
    zone = ZoneInfo("America/New_York")
    gap = resolve_wall_time(datetime(2026, 3, 8, 2, 30), zone)
    overlap = resolve_wall_time(datetime(2026, 11, 1, 1, 30), zone)
    assert gap == instant("2026-03-08T07:00:00Z")
    assert overlap == instant("2026-11-01T05:30:00Z")

    # A historical IANA date-line jump can skip a full local day.
    apia_gap = resolve_wall_time(
        datetime(2011, 12, 30, 0, 0), ZoneInfo("Pacific/Apia")
    )
    assert apia_gap == instant("2011-12-30T10:00:00Z")


def test_timezone_change_recomputes_next_daily_occurrence(store):
    automation = make_reminder(store, timezone_name="America/Sao_Paulo")
    assert automation["next_run_at_utc"] == "2026-10-12T11:00:00.000000+00:00"
    updated = update_timezone(
        store, "owner", automation["id"], "UTC", instant("2026-10-12T07:30:00Z")
    )
    assert updated["timezone"] == "UTC"
    assert updated["next_run_at_utc"] == "2026-10-12T08:00:00.000000+00:00"


def _insert_queued_run(store, automation, *, status="pending", scheduled_at=None):
    scheduled = scheduled_at or automation["next_run_at_utc"]
    run_id = hashlib.sha256(f"{automation['id']}|{status}|{scheduled}".encode()).hexdigest()[:32]
    now = "2026-10-12T07:00:00.000000+00:00"
    with store.transaction() as connection:
        connection.execute(
            """INSERT INTO local_automation_runs (
                id, automation_id, scheduled_for_utc, idempotency_key, workflow_version,
                status, attempts, next_attempt_at_utc, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (run_id, automation["id"], scheduled, f"{automation['id']}:{scheduled}",
             automation["workflow_version"], status, scheduled, now, now),
        )
    return run_id


def test_timezone_change_supersedes_old_queued_occurrence(store):
    automation = make_reminder(store, timezone_name="America/Sao_Paulo")
    old_run_id = _insert_queued_run(store, automation)
    old_due = instant(automation["next_run_at_utc"])

    updated = update_timezone(
        store, "owner", automation["id"], "Pacific/Honolulu", instant("2026-10-12T07:30:00Z")
    )
    assert updated["next_run_at_utc"] == "2026-10-12T18:00:00.000000+00:00"
    with store.transaction() as connection:
        run = connection.execute(
            "SELECT status, error_code FROM local_automation_runs WHERE id=?", (old_run_id,)
        ).fetchone()
    assert tuple(run) == ("superseded", "timezone_changed")

    scheduler = LocalAutomationScheduler(store, clock=lambda: old_due)
    built = []
    scheduler._build_result = lambda *_: built.append(True) or ("unexpected", [])
    assert scheduler.run_due(old_due) == 0
    assert built == []


def test_pause_resume_and_delete_supersede_unstarted_occurrences(store):
    automation = make_reminder(store)
    now = instant("2026-10-12T07:05:00Z")
    pause_run = _insert_queued_run(store, automation)
    paused = control_automation(
        store, owner="owner", automation_id=automation["id"], action="pause", now=now
    )
    assert paused["state"] == "paused"
    with store.transaction() as connection:
        run = connection.execute(
            "SELECT status, error_code FROM local_automation_runs WHERE id=?", (pause_run,)
        ).fetchone()
    assert tuple(run) == ("superseded", "schedule_paused")

    # A stale queued row left by an older build must not run after resume either.
    stale_run = _insert_queued_run(
        store, automation, status="retry_wait", scheduled_at="2026-10-12T07:00:00.000000+00:00"
    )
    resumed = control_automation(
        store, owner="owner", automation_id=automation["id"], action="resume", now=now
    )
    assert resumed["state"] == "active"
    with store.transaction() as connection:
        run = connection.execute(
            "SELECT status, error_code FROM local_automation_runs WHERE id=?", (stale_run,)
        ).fetchone()
    assert tuple(run) == ("superseded", "schedule_resumed")

    delete_run = _insert_queued_run(
        store, automation, status="deferred", scheduled_at="2026-10-12T07:01:00.000000+00:00"
    )
    deleted = control_automation(
        store, owner="owner", automation_id=automation["id"], action="delete", now=now
    )
    assert deleted["state"] == "deleted"
    with store.transaction() as connection:
        run = connection.execute(
            "SELECT status, error_code FROM local_automation_runs WHERE id=?", (delete_run,)
        ).fetchone()
    assert tuple(run) == ("superseded", "schedule_deleted")


def test_repeated_ticks_and_concurrent_workers_create_one_idempotent_run(store):
    automation = make_reminder(store)
    due = instant(automation["next_run_at_utc"])
    scheduler = LocalAutomationScheduler(store, clock=lambda: due)
    built = 0
    lock = threading.Lock()

    def build(_automation, _now):
        nonlocal built
        with lock:
            built += 1
        return "Lembrete local", [{"source": "user-authored-reminder", "id": automation["id"]}]

    scheduler._build_result = build
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: scheduler.run_due(due), range(8)))
    scheduler.run_due(due)
    runs = list_runs(store, "owner", automation["id"])
    assert built == 1
    assert len(runs) == 1
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["attempts"] == 1


def test_restart_marks_due_run_missed_and_recovery_requires_explicit_control(store, encrypted_store_factory):
    automation = make_reminder(store)
    due = instant(automation["next_run_at_utc"])
    reopened_store = encrypted_store_factory(store.path)
    reopened_store.initialize()
    scheduler = LocalAutomationScheduler(reopened_store)
    assert scheduler.startup_reconcile(due.replace(hour=9)) == 1
    assert scheduler.startup_reconcile(due.replace(hour=9)) == 0
    run = list_runs(reopened_store, "owner", automation["id"])[0]
    assert run["status"] == "missed"
    assert scheduler.run_due(due.replace(hour=9)) == 0

    control_automation(
        reopened_store,
        owner="owner",
        automation_id=automation["id"],
        action="recover",
        run_id=run["id"],
        now=due.replace(hour=9),
    )
    assert scheduler.recover(run["id"], due.replace(hour=9))
    assert list_runs(reopened_store, "owner", automation["id"])[0]["status"] == "succeeded"


def test_missed_one_time_run_can_be_recovered_only_after_explicit_action(store):
    automation = make_reminder(
        store, recurrence="once", local_schedule="2026-10-12T08:00",
        now=instant("2026-10-12T07:00:00Z"),
    )
    due = instant(automation["next_run_at_utc"])
    scheduler = LocalAutomationScheduler(store)
    assert scheduler.startup_reconcile(due.replace(hour=9)) == 1
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "missed"
    assert get_automation(store, "owner", automation["id"])["state"] == "completed"
    assert not scheduler.recover(run["id"], due.replace(hour=9))
    control_automation(
        store, owner="owner", automation_id=automation["id"],
        action="recover", run_id=run["id"], now=due.replace(hour=9),
    )
    assert scheduler.recover(run["id"], due.replace(hour=9))
    assert get_automation(store, "owner", automation["id"])["state"] == "completed"
    assert list_runs(store, "owner", automation["id"])[0]["status"] == "succeeded"


def test_delayed_active_poll_records_missed_without_running(store):
    automation = make_reminder(store, recurrence="once", local_schedule="2026-10-12T08:00")
    scheduler = LocalAutomationScheduler(store)
    assert scheduler.run_due(instant("2026-10-12T08:05:00Z")) == 1
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "missed"
    assert run["error_code"] == "late_run"
    assert get_automation(store, "owner", automation["id"])["state"] == "completed"


def test_delayed_retry_after_machine_sleep_requires_manual_recovery(store):
    automation = make_reminder(store)
    due = instant(automation["next_run_at_utc"])
    scheduler = LocalAutomationScheduler(store)
    calls = 0

    def fails_once(_automation, _now):
        nonlocal calls
        calls += 1
        raise sqlite3.OperationalError("temporary test failure")

    scheduler._build_result = fails_once
    scheduler.run_due(due)
    retry_at = due + timedelta(seconds=15)
    assert list_runs(store, "owner", automation["id"])[0]["status"] == "retry_wait"

    assert scheduler.run_due(retry_at + timedelta(minutes=2, seconds=1)) == 1
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "missed"
    assert run["error_code"] == "late_run"
    assert run["attempts"] == 1
    assert calls == 1


def test_quiet_hours_run_delayed_beyond_grace_is_missed(store):
    automation = make_reminder(
        store,
        recurrence="daily",
        local_schedule="22:30",
        now=instant("2026-10-12T07:00:00Z"),
        quiet_start="22:00",
        quiet_end="07:00",
    )
    scheduler = LocalAutomationScheduler(store)
    due = instant(automation["next_run_at_utc"])
    assert scheduler.run_due(due) == 0
    retry_at = instant("2026-10-13T07:00:00Z")
    assert scheduler.run_due(retry_at + timedelta(minutes=2, seconds=1)) == 1
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "missed"
    assert run["error_code"] == "late_run"
    assert run["attempts"] == 0


def test_quiet_hours_defer_until_end_then_run_once(store, encrypted_store_factory):
    automation = make_reminder(
        store,
        recurrence="daily",
        local_schedule="22:30",
        now=instant("2026-10-12T07:00:00Z"),
        quiet_start="22:00",
        quiet_end="07:00",
    )
    scheduler = LocalAutomationScheduler(store)
    due = instant(automation["next_run_at_utc"])
    assert scheduler.run_due(due) == 0
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "deferred"
    assert run["attempts"] == 0
    reopened_store = encrypted_store_factory(store.path)
    reopened_store.initialize()
    restarted_scheduler = LocalAutomationScheduler(reopened_store)
    assert restarted_scheduler.startup_reconcile(instant("2026-10-13T02:00:00Z")) == 0
    restarted_scheduler._build_result = lambda *_: ("Lembrete local", [])
    assert restarted_scheduler.run_due(instant("2026-10-13T07:00:00Z")) == 1
    assert list_runs(reopened_store, "owner", automation["id"])[0]["status"] == "succeeded"


def test_retry_budget_is_two_and_final_output_is_idempotent(store):
    automation = make_reminder(store)
    due = instant(automation["next_run_at_utc"])
    scheduler = LocalAutomationScheduler(store)
    calls = 0

    def flaky(_automation, _now):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise sqlite3.OperationalError("temporary test failure")
        return "um rascunho local", [{"source": "user-authored-reminder", "id": automation["id"]}]

    scheduler._build_result = flaky
    scheduler.run_due(due)
    scheduler.run_due(due.replace(second=15))
    scheduler.run_due(due.replace(second=45))
    scheduler.run_due(due.replace(second=45))
    run = list_runs(store, "owner", automation["id"])[0]
    assert calls == 3
    assert run["attempts"] == 3
    assert run["status"] == "succeeded"
    assert get_run(store, "owner", automation["id"], run["id"])["result_text"] == "um rascunho local"


def test_failed_retry_budget_stops_after_two_retries(store):
    automation = make_reminder(store)
    due = instant(automation["next_run_at_utc"])
    scheduler = LocalAutomationScheduler(store)
    calls = 0

    def always_fails(_automation, _now):
        nonlocal calls
        calls += 1
        raise sqlite3.OperationalError("temporary test failure")

    scheduler._build_result = always_fails
    scheduler.run_due(due)
    scheduler.run_due(due.replace(second=15))
    scheduler.run_due(due.replace(second=45))
    run = list_runs(store, "owner", automation["id"])[0]
    assert calls == 3
    assert run["attempts"] == 3
    assert run["status"] == "failed"
    assert run["error_code"] == "storage_temporary"


def test_restart_preserves_retry_wait_until_its_scheduled_retry(store):
    automation = make_reminder(store)
    due = instant(automation["next_run_at_utc"])
    first_scheduler = LocalAutomationScheduler(store)
    calls = 0

    def fails_once(_automation, _now):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.OperationalError("temporary test failure")
        return "lembrete local", [{"source": "user-authored-reminder", "id": automation["id"]}]

    first_scheduler._build_result = fails_once
    first_scheduler.run_due(due)
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "retry_wait"
    assert run["next_attempt_at_utc"] == (due + timedelta(seconds=15)).isoformat(timespec="microseconds")

    restarted_scheduler = LocalAutomationScheduler(store)
    assert restarted_scheduler.startup_reconcile(due + timedelta(seconds=5)) == 0
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "retry_wait"
    assert calls == 1

    restarted_scheduler._build_result = fails_once
    assert restarted_scheduler.run_due(due + timedelta(seconds=15)) == 1
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "succeeded"
    assert run["attempts"] == 2
    assert calls == 2


def test_restart_does_not_complete_one_time_schedule_before_retry_due(store, encrypted_store_factory):
    automation = make_reminder(
        store, recurrence="once", local_schedule="2026-10-12T08:00",
    )
    due = instant(automation["next_run_at_utc"])
    first_scheduler = LocalAutomationScheduler(store)

    def fails_once(_automation, _now):
        raise sqlite3.OperationalError("temporary test failure")

    first_scheduler._build_result = fails_once
    assert first_scheduler.run_due(due) == 1
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "retry_wait"
    assert get_automation(store, "owner", automation["id"])["state"] == "active"

    retry_at = due + timedelta(seconds=15)
    reopened_store = encrypted_store_factory(store.path)
    reopened_store.initialize()
    restarted_scheduler = LocalAutomationScheduler(reopened_store)
    assert restarted_scheduler.startup_reconcile(due + timedelta(seconds=5)) == 0
    assert get_automation(reopened_store, "owner", automation["id"])["state"] == "active"
    restarted_scheduler._build_result = lambda *_: ("lembrete local", [])
    assert restarted_scheduler.run_due(retry_at) == 1
    assert list_runs(reopened_store, "owner", automation["id"])[0]["status"] == "succeeded"
    assert get_automation(reopened_store, "owner", automation["id"])["state"] == "completed"


def test_manual_retry_also_respects_three_attempt_total(store):
    automation = make_reminder(store)
    due = instant(automation["next_run_at_utc"])
    scheduler = LocalAutomationScheduler(store)
    calls = 0

    def always_fails(_automation, _now):
        nonlocal calls
        calls += 1
        raise AutomationError("source_unavailable")

    scheduler._build_result = always_fails
    scheduler.run_due(due)
    run = list_runs(store, "owner", automation["id"])[0]
    assert run["status"] == "failed" and run["attempts"] == 1
    for attempt, seconds in ((2, 10), (3, 20)):
        control_automation(
            store, owner="owner", automation_id=automation["id"],
            action="retry", run_id=run["id"], now=due.replace(second=seconds),
        )
        scheduler.run_due(due.replace(second=seconds))
        run = list_runs(store, "owner", automation["id"])[0]
        assert run["attempts"] == attempt
    assert run["status"] == "failed" and run["attempts"] == 3
    with pytest.raises(AutomationError):
        control_automation(
            store, owner="owner", automation_id=automation["id"],
            action="retry", run_id=run["id"], now=due.replace(second=30),
        )


def test_pause_resume_delete_and_validation_are_persistent(store):
    automation = make_reminder(store)
    now = instant("2026-10-12T07:05:00Z")
    paused = control_automation(
        store, owner="owner", automation_id=automation["id"], action="pause", now=now
    )
    assert paused["state"] == "paused" and paused["next_run_at_utc"] is None
    timezone_changed = update_timezone(store, "owner", automation["id"], "UTC", now)
    assert timezone_changed["state"] == "paused"
    assert timezone_changed["next_run_at_utc"] is None
    resumed = control_automation(
        store, owner="owner", automation_id=automation["id"], action="resume", now=now
    )
    assert resumed["state"] == "active"
    deleted = control_automation(
        store, owner="owner", automation_id=automation["id"], action="delete", now=now
    )
    assert deleted["state"] == "deleted"
    with pytest.raises(AutomationError):
        update_timezone(store, "owner", automation["id"], "Not/AZone", now)


def test_create_run_pause_resume_delete_keeps_local_history_without_external_effect(store):
    created = make_reminder(store)
    due = instant(created["next_run_at_utc"])
    scheduler = LocalAutomationScheduler(store, clock=lambda: due)
    assert scheduler.run_due(due) == 1
    history = list_runs(store, "owner", created["id"])
    assert len(history) == 1 and history[0]["status"] == "succeeded"
    paused = control_automation(
        store, owner="owner", automation_id=created["id"], action="pause", now=due
    )
    assert paused["state"] == "paused" and paused["next_run_at_utc"] is None
    resumed = control_automation(
        store, owner="owner", automation_id=created["id"], action="resume", now=due
    )
    assert resumed["state"] == "active" and resumed["next_run_at_utc"] is not None
    deleted = control_automation(
        store, owner="owner", automation_id=created["id"], action="delete", now=due + timedelta(minutes=1)
    )
    assert deleted["state"] == "deleted"
    retained = list_runs(store, "owner", created["id"])
    assert len(retained) == 1 and retained[0]["status"] == "succeeded"
    assert retained[0]["id"] == history[0]["id"]
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM synthetic_effect_ledger").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM synthetic_effect_outbox").fetchone()[0] == 0


def test_new_migration_upgrades_previous_database_and_starts_empty(tmp_path, encrypted_store_factory):
    older = tmp_path / "older-migrations"
    older.mkdir()
    for migration in MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"):
        if migration.name != "0020_local_automations.sql":
            copyfile(migration, older / migration.name)
    path = tmp_path / "private" / "memory.sqlite3"
    encrypted_store_factory(path, migrations_dir=older).initialize()
    upgraded = encrypted_store_factory(path)
    upgraded.initialize()
    with upgraded.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM local_automations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM local_automation_runs").fetchone()[0] == 0
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()[0] == "0027_memory_capture_revisions"
        assert connection.execute("SELECT COUNT(*) FROM synthetic_effect_outbox").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM synthetic_effect_ledger").fetchone()[0] == 0
