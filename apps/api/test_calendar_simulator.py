from __future__ import annotations

import sqlite3
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from calendar_simulator import (
    CALENDAR_SOURCE, CalendarCursor, CalendarProvider, CalendarProviderError, CalendarSyncService,
)
from local_security import reset_state
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
    assert client.get("/real/events").status_code == 403
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
