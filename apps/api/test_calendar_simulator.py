from __future__ import annotations

import sqlite3
import hashlib
import socket
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from calendar_simulator import (
    CALENDAR_SOURCE, CalendarCursor, CalendarProvider, CalendarProviderError, CalendarSyncService,
)
from local_security import authorized_calendar_domains, calendar_grant_guard, reset_state
from main import create_app
from memory_models import EventRecord, ProvenanceRecord, ReadScope
from memory_store import EventIdentityConflict, SQLiteMemoryStore
from server_config import LocalServerConfig

PASSPHRASE = "senha-sintetica-de-regressao"
ORIGIN = "http://127.0.0.1:3000"
LETTERS = "abcdefgh"


@pytest.fixture
def client(tmp_path, monkeypatch):
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    app = create_app(
        LocalServerConfig(), database_path=tmp_path / "private" / "memory.sqlite3"
    )
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50991)) as test_client:
        yield test_client
    reset_state()


def login(client: TestClient) -> tuple[str, str]:
    response = client.post("/real/session", json={"passphrase": PASSPHRASE}, headers={"origin": ORIGIN})
    assert response.status_code == 201
    token = client.cookies.get("jarvis_session")
    from local_security import _sessions
    csrf = next(session.csrf_token for session in _sessions.values() if session.token == token)
    return token, csrf


def grant(client: TestClient, csrf: str, domains: list[str]) -> str:
    response = client.post(
        "/real/grants",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={
            "connector": "calendar_sim",
            "permission": "read",
            "resource_ids": ["calendar:synthetic-primary"],
            "domain_ids": domains,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def classify(client: TestClient, csrf: str, calendar_letter: str, domain_letter: str) -> None:
    response = client.put(
        f"/real/calendar-sim/calendars/sim_calendar_{calendar_letter}/classification",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"domain_id": f"dom_synthetic_{domain_letter}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["provider_mode"] == "simulated"


def sync_one(client: TestClient, csrf: str, letter: str):
    return client.post(
        "/real/calendar-sim/sync",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"calendar_id": f"sim_calendar_{letter}"},
    )


@contextmanager
def actual_http_server(tmp_path):
    """Run a loopback Uvicorn socket for browser CORS preflight regression tests."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    app = create_app(
        LocalServerConfig(host="127.0.0.1", port=port),
        database_path=tmp_path / "actual-http" / "memory.sqlite3",
    )
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("servidor HTTP local não iniciou no prazo")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_simulator_is_session_protected_and_demo_remains_separate(client):
    assert client.get("/real/calendar-sim/calendars").status_code == 401
    assert client.post("/real/calendar-sim/sync", json={}, headers={"origin": ORIGIN}).status_code == 401
    assert "evt_001" in {event["id"] for event in client.get("/events").json()}
    assert client.get("/events").headers["x-jarvis-dataset"] == "demo"
    assert client.get("/real/calendar-sim/calendars").headers["x-jarvis-dataset"] == "real"


def test_calendar_mutations_require_allowed_origin_and_csrf(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    path = "/real/calendar-sim/calendars/sim_calendar_a/classification"
    assert client.put(path, json={"domain_id": "dom_synthetic_a"}, headers={"origin": ORIGIN}).status_code == 403
    assert client.put(
        path,
        json={"domain_id": "dom_synthetic_a"},
        headers={"origin": "https://evil.invalid", "x-csrf-token": csrf},
    ).status_code == 403
    classify(client, csrf, "a", "a")
    assert client.post(
        "/real/calendar-sim/sync", json={"calendar_id": "sim_calendar_a"},
        headers={"origin": ORIGIN, "x-csrf-token": "csrf-from-another-session"},
    ).status_code == 403


def test_calendar_requires_explicit_mapping_and_missing_grant_is_quarantined(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    unclassified = client.post(
        "/real/calendar-sim/sync",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={},
    )
    assert unclassified.status_code == 200
    assert unclassified.json()["events_written"] == 0
    assert len(unclassified.json()["quarantined"]) == 8
    assert {entry["reason"] for entry in unclassified.json()["quarantined"]} == {"unclassified"}
    assert client.get("/real/events").status_code == 200
    assert client.get("/real/events").json() == []
    with sqlite3.connect(client.app.state.memory_store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0

    service = client.app.state.calendar_sync_service
    service.classify("sim_calendar_b", "dom_synthetic_b")
    partial = service.sync(frozenset({"dom_synthetic_a"}))
    assert any(item.calendar_id == "sim_calendar_b" and item.reason == "grant_missing" for item in partial.quarantined)
    assert all(state.calendar_id != "sim_calendar_b" for state in partial.states)
    assert client.app.state.memory_store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary", domain_ids=frozenset({"dom_synthetic_b"}))
    ]) == []


def test_paginated_sync_preserves_timezone_provenance_and_is_idempotent(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    provider = CalendarProvider(page_size=1)
    client.app.state.calendar_sim_provider = provider
    client.app.state.calendar_sync_service = CalendarSyncService(client.app.state.memory_store, provider)

    first = sync_one(client, csrf, "a")
    assert first.status_code == 200, first.text
    assert first.json()["events_written"] == 2
    second = sync_one(client, csrf, "a")
    assert second.status_code == 200, second.text
    assert second.json()["events_written"] == 0

    records = client.app.state.memory_store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary", domain_ids=frozenset({"dom_synthetic_a"}))
    ])
    assert len(records) == 2
    event = records[0].event
    assert event.id.startswith("real_evt_cal_")
    assert event.provenance.external_ref.startswith("sim_calendar_a:evt-synth-a-")
    assert event.provenance.classification_method == "human_review"
    assert event.provenance.classified_at is not None
    assert event.payload_minimized["calendar_id"] == "sim_calendar_a"
    assert event.payload_minimized["event_time_zone"] == "America/Sao_Paulo"
    assert event.payload_minimized["end_at"]
    assert event.payload_minimized["provider_updated_at"]
    assert event.dataset == "real"
    assert records[0].source.id == CALENDAR_SOURCE.id
    response_event = client.get("/real/events").json()[0]
    assert response_event["source_id"] == CALENDAR_SOURCE.id
    assert response_event["calendar_id"] == "sim_calendar_a"
    assert response_event["calendar_name"] == "Calendário sintético A"
    assert response_event["calendar_time_zone"] == "America/Sao_Paulo"
    assert response_event["event_time_zone"] == "America/Sao_Paulo"
    assert response_event["end_at"]
    assert response_event["provider_updated_at"]


def test_cancellation_is_soft_deleted_and_not_returned_in_reads(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    service = client.app.state.calendar_sync_service
    provider = client.app.state.calendar_sim_provider
    assert sync_one(client, csrf, "a").status_code == 200
    provider.cancel_event("sim_calendar_a", "evt-synth-a-1")
    checkpoint = client.app.state.memory_store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert checkpoint is not None
    tombstone_page = provider.list_events(
        "sim_calendar_a", CalendarCursor(sync_token=checkpoint.sync_token)
    )
    assert [(item.calendar_id, item.event_id) for item in tombstone_page.deletions] == [
        ("sim_calendar_a", "evt-synth-a-1")
    ]

    incremental = sync_one(client, csrf, "a")
    assert incremental.status_code == 200, incremental.text
    assert incremental.json()["cancellations_applied"] == 1
    visible = client.get("/real/events")
    assert visible.status_code == 200
    assert len(visible.json()) == 1
    with sqlite3.connect(service.store.path) as connection:
        cancelled = connection.execute(
            "SELECT cancelled_at FROM events WHERE id IN (SELECT event_id FROM event_provenance WHERE external_ref=?)",
            ("sim_calendar_a:evt-synth-a-1",),
        ).fetchone()
    assert cancelled is not None and cancelled[0] is not None


def test_republished_event_reactivates_same_identity_after_cancellation(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    provider = client.app.state.calendar_sim_provider
    service = client.app.state.calendar_sync_service
    assert sync_one(client, csrf, "a").status_code == 200
    provider.cancel_event("sim_calendar_a", "evt-synth-a-1")
    assert sync_one(client, csrf, "a").status_code == 200
    assert len(client.get("/real/events").json()) == 1

    cancelled = provider.get_event("sim_calendar_a", "evt-synth-a-1")
    assert cancelled is not None
    provider.publish_event(cancelled.model_copy(update={
        "status": "confirmed",
        "summary": "Compromisso sintético reativado",
        "updated_at": datetime.now(timezone.utc),
    }))
    reactivated = sync_one(client, csrf, "a")
    assert reactivated.status_code == 200
    assert len(client.get("/real/events").json()) == 2
    with sqlite3.connect(service.store.path) as connection:
        state = connection.execute(
            "SELECT cancelled_at FROM events WHERE id IN (SELECT event_id FROM event_provenance WHERE external_ref=?)",
            ("sim_calendar_a:evt-synth-a-1",),
        ).fetchone()
    assert state == (None,)


def test_invalid_cursor_recovers_with_full_snapshot_without_duplicates(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    assert sync_one(client, csrf, "a").status_code == 200
    provider = client.app.state.calendar_sim_provider
    provider.invalidate_cursors("sim_calendar_a")
    checkpoint = client.app.state.memory_store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert checkpoint is not None
    with pytest.raises(CalendarProviderError) as invalid:
        provider.list_events("sim_calendar_a", CalendarCursor(sync_token=checkpoint.sync_token))
    assert invalid.value.status_code == 410

    recovered = sync_one(client, csrf, "a")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["events_written"] == 2
    records = client.app.state.memory_store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary", domain_ids=frozenset({"dom_synthetic_a"}))
    ])
    assert len(records) == 2


def test_simulated_provider_failure_preserves_cursor_and_recovers(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    provider = client.app.state.calendar_sim_provider
    provider.fail_next("sim_calendar_a")

    failed = sync_one(client, csrf, "a")
    assert failed.status_code == 200
    assert failed.json()["states"][0]["status"] == "error"
    checkpoint = client.app.state.memory_store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert checkpoint is not None and checkpoint.sync_token is None
    assert checkpoint.error_code == "simulated_network"
    assert client.app.state.memory_store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary", domain_ids=frozenset({"dom_synthetic_a"}))
    ]) == []

    recovered = sync_one(client, csrf, "a")
    assert recovered.status_code == 200
    assert recovered.json()["states"][0]["status"] == "simulated"
    assert recovered.json()["events_written"] == 2


def test_revocation_blocks_sync_and_existing_event_reads(client):
    _token, csrf = login(client)
    grant_id = grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    assert sync_one(client, csrf, "a").status_code == 200
    assert client.get("/real/events").status_code == 200

    revoked = client.post(
        f"/real/grants/{grant_id}/revoke",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
    )
    assert revoked.status_code == 200
    assert client.get("/real/events").status_code == 403
    assert client.get("/real/briefing").status_code == 403
    assert sync_one(client, csrf, "a").status_code == 403


def test_eight_explicit_domain_mappings_remain_isolated(client):
    _token, csrf = login(client)
    grant(client, csrf, [f"dom_synthetic_{letter}" for letter in LETTERS])
    for letter in LETTERS:
        classify(client, csrf, letter, letter)
    report = client.post(
        "/real/calendar-sim/sync",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={},
    )
    assert report.status_code == 200, report.text
    assert report.json()["events_written"] == 16
    assert report.json()["quarantined"] == []

    for letter in LETTERS:
        domain = f"dom_synthetic_{letter}"
        items = client.get("/real/events", params={"domain_id": domain}).json()
        assert len(items) == 2
        assert {item["domain_id"] for item in items} == {domain}
    all_events = client.get("/real/events").json()
    assert len(all_events) == 16
    assert {event["domain_id"] for event in all_events} == {f"dom_synthetic_{letter}" for letter in LETTERS}


def test_concurrent_syncs_advance_cursor_atomically_without_duplicates(client):
    service = client.app.state.calendar_sync_service
    service.classify("sim_calendar_a", "dom_synthetic_a")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a"), range(2)))
    assert all(result.dataset == "real" for result in results)
    records = service.store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary", domain_ids=frozenset({"dom_synthetic_a"}))
    ])
    assert len(records) == 2
    assert len({record.event.provenance.external_ref for record in records}) == 2


def test_sync_cursor_and_explicit_mapping_survive_store_restart(client):
    service = client.app.state.calendar_sync_service
    service.classify("sim_calendar_a", "dom_synthetic_a")
    first = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert first.events_written == 2
    old_checkpoint = service.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert old_checkpoint is not None and old_checkpoint.sync_token

    reopened_store = SQLiteMemoryStore(service.store.path)
    reopened_store.initialize()
    restarted_service = CalendarSyncService(reopened_store, service.provider)
    persisted = reopened_store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert persisted is not None
    assert persisted.domain_id == "dom_synthetic_a"
    assert persisted.sync_token == old_checkpoint.sync_token
    repeated = restarted_service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert repeated.events_written == 0
    assert len(reopened_store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary", domain_ids=frozenset({"dom_synthetic_a"}))
    ])) == 2


def test_page_conflict_rolls_back_events_provenance_audit_and_cursor(client):
    service = client.app.state.calendar_sync_service
    service.classify("sim_calendar_a", "dom_synthetic_a")
    event_id = "evt-synth-a-1"
    digest = hashlib.sha256(
        f"real|{CALENDAR_SOURCE.id}|sim_calendar_a|{event_id}".encode()
    ).hexdigest()
    observed = datetime.now(timezone.utc)
    service.store.save_event(EventRecord(
        id=f"real_evt_cal_{digest}",
        event_type="appointment",
        title="Registro sintético anterior",
        domain_id="dom_synthetic_a",
        occurred_at=observed,
        provenance=ProvenanceRecord(
            source_id=CALENDAR_SOURCE.id,
            external_ref="sim_calendar_a:other-external-event",
            observed_at=observed,
            classification_method="human_review",
            classified_at=observed,
        ),
    ))
    with pytest.raises(EventIdentityConflict):
        service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")

    checkpoint = service.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert checkpoint is not None and checkpoint.sync_token is None and checkpoint.page_token is None
    records = service.store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary", domain_ids=frozenset({"dom_synthetic_a"}))
    ])
    assert len(records) == 1
    assert records[0].event.title == "Registro sintético anterior"
    with sqlite3.connect(service.store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM event_provenance").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_entries WHERE operation='event_write'").fetchone()[0] == 1


def test_sync_state_becomes_stale_after_24_hours_and_never_claims_real_connection(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    report = sync_one(client, csrf, "a")
    assert report.status_code == 200
    assert report.json()["states"][0]["provider_mode"] == "simulated"
    assert report.json()["states"][0]["status"] == "simulated"
    service = client.app.state.calendar_sync_service
    old = datetime.now(timezone.utc) - timedelta(hours=24, seconds=1)
    with sqlite3.connect(service.store.path) as connection:
        connection.execute(
            "UPDATE calendar_sync_states SET last_success_at=?, sync_status='simulated' WHERE source_id=? AND calendar_id=?",
            (old.isoformat(), CALENDAR_SOURCE.id, "sim_calendar_a"),
        )
    state = client.get("/real/calendar-sim/state")
    assert state.status_code == 200
    a_state = next(item for item in state.json()["states"] if item["calendar_id"] == "sim_calendar_a")
    assert a_state["status"] == "stale"
    assert a_state["provider_mode"] == "simulated"


def test_unknown_domain_and_calendar_cannot_be_classified(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    unknown_domain = client.put(
        "/real/calendar-sim/calendars/sim_calendar_a/classification",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"domain_id": "dom_unknown"},
    )
    assert unknown_domain.status_code == 422
    unknown_calendar = client.put(
        "/real/calendar-sim/calendars/sim_calendar_z/classification",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"domain_id": "dom_synthetic_a"},
    )
    assert unknown_calendar.status_code == 404


def test_classification_requires_matching_active_domain_grant_and_is_immutable(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    forbidden = client.put(
        "/real/calendar-sim/calendars/sim_calendar_b/classification",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"domain_id": "dom_synthetic_b"},
    )
    assert forbidden.status_code == 403

    classify(client, csrf, "a", "a")
    grant(client, csrf, ["dom_synthetic_b"])
    changed = client.put(
        "/real/calendar-sim/calendars/sim_calendar_a/classification",
        headers={"origin": ORIGIN, "x-csrf-token": csrf},
        json={"domain_id": "dom_synthetic_b"},
    )
    assert changed.status_code == 409


def test_revocation_completed_before_page_commit_prevents_rows_and_cursor_advance(client):
    _token, csrf = login(client)
    grant_id = grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    service = client.app.state.calendar_sync_service
    entered_guard = threading.Event()
    release_guard = threading.Event()

    @contextmanager
    def pause_before_authorization_lock(domain):
        entered_guard.set()
        assert release_guard.wait(timeout=5)
        with calendar_grant_guard("owner", frozenset({domain})):
            yield

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            service.sync,
            frozenset({"dom_synthetic_a"}),
            "sim_calendar_a",
            is_domain_authorized=lambda domain: domain in authorized_calendar_domains("owner"),
            authorization_guard=pause_before_authorization_lock,
        )
        assert entered_guard.wait(timeout=5)
        revoked = client.post(
            f"/real/grants/{grant_id}/revoke",
            headers={"origin": ORIGIN, "x-csrf-token": csrf},
        )
        assert revoked.status_code == 200
        release_guard.set()
        report = pending.result(timeout=5)

    checkpoint = service.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    with sqlite3.connect(service.store.path) as connection:
        event_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert report.quarantined[0].reason == "grant_missing"
    assert event_count == 0
    assert checkpoint is not None
    assert checkpoint.sync_token is None and checkpoint.page_token is None
    assert checkpoint.full_sync_id is None


def test_revocation_after_commit_before_http_response_suppresses_report(client):
    _token, csrf = login(client)
    grant_id = grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    service = client.app.state.calendar_sync_service
    original_sync = service.sync
    sync_committed = threading.Event()
    release_response = threading.Event()

    def pause_after_sync(*args, **kwargs):
        report = original_sync(*args, **kwargs)
        sync_committed.set()
        assert release_response.wait(timeout=5)
        return report

    service.sync = pause_after_sync
    token = client.cookies.get("jarvis_session")
    parallel_client = TestClient(
        client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50992)
    )
    parallel_client.cookies.set("jarvis_session", token)
    request_headers = {"origin": ORIGIN, "x-csrf-token": csrf}

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            client.post,
            "/real/calendar-sim/sync",
            json={"calendar_id": "sim_calendar_a"},
            headers=request_headers,
        )
        assert sync_committed.wait(timeout=5)
        revoked = parallel_client.post(
            f"/real/grants/{grant_id}/revoke", headers=request_headers
        )
        assert revoked.status_code == 200
        release_response.set()
        response = pending.result(timeout=5)

    assert response.status_code == 403
    assert "dom_synthetic_a" not in response.text
    assert "events_written" not in response.text
    assert client.get("/real/events").status_code == 403
    with sqlite3.connect(service.store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_complete_snapshot_reconciles_missing_event_and_later_reappearance(client):
    _token, csrf = login(client)
    grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    provider = CalendarProvider(page_size=1)
    service = CalendarSyncService(client.app.state.memory_store, provider)
    assert service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a").events_written == 2

    removed = provider._current["sim_calendar_a"].pop("evt-synth-a-1")
    incremental = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert incremental.cancellations_applied == 0
    with sqlite3.connect(service.store.path) as connection:
        not_inferred_deleted = connection.execute(
            "SELECT cancelled_at FROM events WHERE id IN "
            "(SELECT event_id FROM event_provenance WHERE external_ref=?)",
            ("sim_calendar_a:evt-synth-a-1",),
        ).fetchone()
    assert not_inferred_deleted == (None,)

    provider.invalidate_cursors("sim_calendar_a")
    reconciled = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert reconciled.cancellations_applied == 1
    with sqlite3.connect(service.store.path) as connection:
        row = connection.execute(
            "SELECT e.cancelled_at, p.external_ref FROM events e JOIN event_provenance p ON p.event_id=e.id "
            "WHERE p.external_ref=?", ("sim_calendar_a:evt-synth-a-1",)
        ).fetchone()
    assert row is not None and row[0] is not None

    provider.publish_event(removed.model_copy(update={
        "summary": "Compromisso sintético reaparecido",
        "updated_at": datetime.now(timezone.utc),
    }))
    reappeared = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert reappeared.events_written == 1
    records = service.store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary",
                  domain_ids=frozenset({"dom_synthetic_a"}))
    ])
    assert len(records) == 2
    assert any(item.event.title == "Compromisso sintético reaparecido" for item in records)
    assert any(item.event.provenance.external_ref == row[1] and item.event.cancelled_at is None
               for item in records)


def test_partial_full_snapshot_failure_does_not_reconcile_until_retry(client):
    service = client.app.state.calendar_sync_service
    service.classify("sim_calendar_a", "dom_synthetic_a")
    provider = CalendarProvider(page_size=1)
    extra = provider.get_event("sim_calendar_a", "evt-synth-a-1")
    assert extra is not None
    provider.publish_event(extra.model_copy(update={
        "event_id": "evt-synth-a-3",
        "summary": "Terceiro evento sintético",
    }))
    service = CalendarSyncService(service.store, provider)
    initial = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert initial.events_written == 3

    provider._current["sim_calendar_a"].pop("evt-synth-a-3")
    provider.invalidate_cursors("sim_calendar_a")
    original_apply = service.store.apply_calendar_page
    injected_failure = {"done": False}

    def commit_then_inject_provider_failure(**kwargs):
        result = original_apply(**kwargs)
        if not injected_failure["done"] and kwargs["completed_at"] is None:
            injected_failure["done"] = True
            provider.fail_next("sim_calendar_a")
        return result

    service.store.apply_calendar_page = commit_then_inject_provider_failure
    failed = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert failed.states[0].status == "error"
    with sqlite3.connect(service.store.path) as connection:
        before_retry = connection.execute(
            "SELECT cancelled_at FROM events WHERE id IN "
            "(SELECT event_id FROM event_provenance WHERE external_ref=?)",
            ("sim_calendar_a:evt-synth-a-3",),
        ).fetchone()
        staged = connection.execute(
            "SELECT COUNT(*) FROM calendar_sync_seen_events WHERE calendar_id='sim_calendar_a'"
        ).fetchone()[0]
    assert before_retry == (None,)
    assert staged == 1

    service.store.apply_calendar_page = original_apply
    retried = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert retried.cancellations_applied == 1
    with sqlite3.connect(service.store.path) as connection:
        after_retry = connection.execute(
            "SELECT cancelled_at FROM events WHERE id IN "
            "(SELECT event_id FROM event_provenance WHERE external_ref=?)",
            ("sim_calendar_a:evt-synth-a-3",),
        ).fetchone()
        staged_after = connection.execute(
            "SELECT COUNT(*) FROM calendar_sync_seen_events WHERE calendar_id='sim_calendar_a'"
        ).fetchone()[0]
    assert after_retry is not None and after_retry[0] is not None
    assert staged_after == 0


def test_revocation_mid_full_snapshot_discards_staging_without_reconciliation(client):
    _token, csrf = login(client)
    grant_id = grant(client, csrf, ["dom_synthetic_a"])
    classify(client, csrf, "a", "a")
    provider = CalendarProvider(page_size=1)
    event = provider.get_event("sim_calendar_a", "evt-synth-a-1")
    assert event is not None
    provider.publish_event(event.model_copy(update={"event_id": "evt-synth-a-3"}))
    service = CalendarSyncService(client.app.state.memory_store, provider)
    authorized = frozenset({"dom_synthetic_a"})
    checker = lambda domain: domain in authorized_calendar_domains("owner")
    guard = lambda domain: calendar_grant_guard("owner", frozenset({domain}))
    assert service.sync(authorized, "sim_calendar_a", is_domain_authorized=checker,
                        authorization_guard=guard).events_written == 3

    provider._current["sim_calendar_a"].pop("evt-synth-a-3")
    provider.invalidate_cursors("sim_calendar_a")
    second_page_guard = threading.Event()
    release_second_page = threading.Event()
    calls = {"count": 0}

    @contextmanager
    def pause_second_page_guard(domain):
        calls["count"] += 1
        if calls["count"] == 2:
            second_page_guard.set()
            assert release_second_page.wait(timeout=5)
        with calendar_grant_guard("owner", frozenset({domain})):
            yield

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.sync, authorized, "sim_calendar_a",
                              is_domain_authorized=checker,
                              authorization_guard=pause_second_page_guard)
        assert second_page_guard.wait(timeout=5)
        revoked = client.post(f"/real/grants/{grant_id}/revoke",
                              headers={"origin": ORIGIN, "x-csrf-token": csrf})
        assert revoked.status_code == 200
        release_second_page.set()
        report = pending.result(timeout=5)

    assert report.quarantined[0].reason == "grant_missing"
    checkpoint = service.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    with sqlite3.connect(service.store.path) as connection:
        missing_event = connection.execute(
            "SELECT cancelled_at FROM events WHERE id IN "
            "(SELECT event_id FROM event_provenance WHERE external_ref=?)",
            ("sim_calendar_a:evt-synth-a-3",),
        ).fetchone()
        staged = connection.execute(
            "SELECT COUNT(*) FROM calendar_sync_seen_events WHERE calendar_id='sim_calendar_a'"
        ).fetchone()[0]
    assert missing_event == (None,)
    assert staged == 0
    assert checkpoint is not None and checkpoint.page_token is None and checkpoint.full_sync_id is None


def test_new_provider_epoch_forces_full_reconciled_sync_after_restart(client):
    service = client.app.state.calendar_sync_service
    service.classify("sim_calendar_a", "dom_synthetic_a")
    old_provider = service.provider
    first = service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert first.events_written == 2
    changed = old_provider.get_event("sim_calendar_a", "evt-synth-a-1")
    assert changed is not None
    old_provider.publish_event(changed.model_copy(update={"summary": "Alterado antes do reinício"}))
    assert service.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a").events_written == 1
    old_checkpoint = service.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert old_checkpoint is not None and old_checkpoint.sync_token is not None

    new_provider = CalendarProvider()
    restarted = CalendarSyncService(service.store, new_provider)
    with pytest.raises(CalendarProviderError) as invalid:
        new_provider.list_events("sim_calendar_a", CalendarCursor(sync_token=old_checkpoint.sync_token))
    assert invalid.value.status_code == 410

    recovered = restarted.sync(frozenset({"dom_synthetic_a"}), "sim_calendar_a")
    assert recovered.events_written == 2
    checkpoint = service.store.get_calendar_checkpoint(CALENDAR_SOURCE.id, "sim_calendar_a")
    assert checkpoint is not None and checkpoint.sync_token != old_checkpoint.sync_token
    assert checkpoint.page_token is None and checkpoint.full_sync_id is None
    records = service.store.list_authorized_events([
        ReadScope(connector="calendar_sim", resource_id="calendar:synthetic-primary",
                  domain_ids=frozenset({"dom_synthetic_a"}))
    ])
    assert len(records) == 2
    assert next(item.event.title for item in records if item.event.provenance.external_ref.endswith("evt-synth-a-1")) == "Compromisso sintético A-1"


def test_real_http_cors_preflight_and_classification_put(tmp_path, monkeypatch):
    reset_state()
    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    with actual_http_server(tmp_path) as base_url:
        with httpx.Client(base_url=base_url, timeout=3, trust_env=False) as http:
            headers = {
                "origin": ORIGIN,
                "access-control-request-method": "PUT",
                "access-control-request-headers": "content-type,x-csrf-token",
            }
            preflight = http.options(
                "/real/calendar-sim/calendars/sim_calendar_a/classification", headers=headers
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == ORIGIN
            assert preflight.headers["access-control-allow-credentials"] == "true"
            assert "PUT" in preflight.headers["access-control-allow-methods"]
            assert preflight.headers["access-control-allow-origin"] != "*"

            login_response = http.post(
                "/real/session", headers={"origin": ORIGIN}, json={"passphrase": PASSPHRASE}
            )
            assert login_response.status_code == 201
            csrf = login_response.json()["csrf_token"]
            grant_response = http.post(
                "/real/grants",
                headers={"origin": ORIGIN, "x-csrf-token": csrf},
                json={
                    "connector": "calendar_sim", "permission": "read",
                    "resource_ids": ["calendar:synthetic-primary"],
                    "domain_ids": ["dom_synthetic_a", "dom_synthetic_b"],
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                },
            )
            assert grant_response.status_code == 201
            classified = http.put(
                "/real/calendar-sim/calendars/sim_calendar_a/classification",
                headers={"origin": ORIGIN, "x-csrf-token": csrf},
                json={"domain_id": "dom_synthetic_a"},
            )
            assert classified.status_code == 200

            external_origin = http.options(
                "/real/calendar-sim/calendars/sim_calendar_b/classification",
                headers={**headers, "origin": "https://outside.invalid"},
            )
            disallowed_method = http.options(
                "/real/calendar-sim/calendars/sim_calendar_b/classification",
                headers={**headers, "access-control-request-method": "PATCH"},
            )
            unexpected_header = http.options(
                "/real/calendar-sim/calendars/sim_calendar_b/classification",
                headers={**headers, "access-control-request-headers": "content-type,x-csrf-token,x-unexpected"},
            )
            denied_put = http.put(
                "/real/calendar-sim/calendars/sim_calendar_b/classification",
                headers={"origin": "https://outside.invalid", "x-csrf-token": csrf},
                json={"domain_id": "dom_synthetic_b"},
            )
            assert external_origin.status_code == 400
            assert disallowed_method.status_code == 400
            assert unexpected_header.status_code == 400
            assert denied_put.status_code == 403
