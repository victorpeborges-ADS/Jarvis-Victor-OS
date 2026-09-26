from __future__ import annotations

import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from shutil import copyfile
from threading import Barrier

import pytest
import httpx
from fastapi.testclient import TestClient

from local_security import Grant, put_grant_for_tests, put_session_for_tests, reset_state
from main import create_app
from memory_store import MIGRATIONS_DIR, SQLiteMemoryStore
from mission_repository import MissionRepository, _store_idempotency
from server_config import LocalServerConfig
from test_missions_api import ORIGIN, PASSPHRASE, client, create, login, mission_grants


def _headers(csrf: str) -> dict[str, str]:
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def _copy_mission(document: dict, suffix: str, *, event_ids: tuple[str, ...] | None = None) -> dict:
    result = copy.deepcopy(document)
    result["id"] = f"mission_import_{suffix}"
    if event_ids is not None:
        assert len(event_ids) == len(result["events"])
        for event, event_id in zip(result["events"], event_ids, strict=True):
            event["id"] = event_id
    return result


def _import(client: TestClient, csrf: str, documents: list[dict], key: str):
    return client.post(
        "/real/missions/import",
        headers=_headers(csrf),
        json={"missions": documents, "idempotency_key": key, "confirm": True},
    )


def _count(database, query: str, parameters: tuple = ()) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute(query, parameters).fetchone()[0]


@pytest.mark.parametrize("duplicate", ["mission", "event"])
def test_duplicate_ids_inside_import_batch_return_422_without_writes(client, duplicate):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, f"batch identity source {duplicate}")["mission"]

    if duplicate == "mission":
        documents = [
            _copy_mission(source, "same_mission_001", event_ids=("event_batch_mission_a1",)),
            _copy_mission(source, "same_mission_001", event_ids=("event_batch_mission_b1",)),
        ]
    else:
        documents = [
            _copy_mission(source, "shared_event_a01", event_ids=("event_batch_shared_01",)),
            _copy_mission(source, "shared_event_b01", event_ids=("event_batch_shared_01",)),
        ]

    response = _import(client, csrf, documents, f"batch-duplicate-{duplicate}-01")

    assert response.status_code == 422
    assert response.json() == {"detail": "lote de importação contém identificadores repetidos"}
    assert all(document["id"] not in response.text for document in documents)
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_idempotency WHERE idempotency_key LIKE 'batch-duplicate-%'") == 0
    assert _count(client.database_path, "SELECT COUNT(*) FROM missions") == 1


def test_repeated_event_id_inside_document_is_reported_in_quarantine(client):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "duplicate event in one document")["mission"]
    invalid = _copy_mission(source, "same_document_001", event_ids=("event_doc_duplicate_01",))
    invalid["events"].append(copy.deepcopy(invalid["events"][0]))

    response = _import(client, csrf, [invalid], "duplicate-event-doc-01")

    assert response.status_code == 200
    assert response.json()["accepted"] == []
    assert response.json()["quarantined"] == [{"index": 0, "reason": "ID de evento repetido no documento"}]
    assert _count(client.database_path, "SELECT COUNT(*) FROM missions") == 1
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_idempotency WHERE idempotency_key='duplicate-event-doc-01'") == 0


def test_successive_exact_import_is_noop_but_changed_mission_body_conflicts(client):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "exact repeat source")["mission"]
    before_events = _count(client.database_path, "SELECT COUNT(*) FROM mission_events")

    repeated = _import(client, csrf, [source], "successive-repeat-001")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["accepted"] == []
    assert repeated.json()["quarantined"] == []
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_events") == before_events

    changed = copy.deepcopy(source)
    changed["title"] = "conteúdo alterado depois da primeira importação"
    conflict = _import(client, csrf, [changed], "successive-change-001")
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "conflito de identidade na importação"}
    assert source["id"] not in conflict.text
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_idempotency WHERE idempotency_key='successive-change-001'") == 0
    reread = client.get(f"/real/missions/{source['id']}", headers={"origin": ORIGIN})
    assert reread.status_code == 200
    assert reread.json()["mission"]["title"] == source["title"]


@pytest.mark.parametrize("change_event_payload", [False, True])
def test_event_id_already_owned_by_another_mission_conflicts_without_leaking_ids(client, change_event_payload):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "persistent event identity source")["mission"]
    event_id = source["events"][0]["id"]
    imported = _copy_mission(source, f"event_conflict_{int(change_event_payload)}")
    if change_event_payload:
        imported["events"][0]["message"] = "conteúdo conflitante sob o mesmo ID"

    response = _import(client, csrf, [imported], f"persisted-event-conflict-{int(change_event_payload)}")

    assert response.status_code == 409
    assert response.json() == {"detail": "conflito de identidade na importação"}
    assert event_id not in response.text
    assert imported["id"] not in response.text
    assert source["id"] not in response.text
    assert _count(client.database_path, "SELECT COUNT(*) FROM missions WHERE id=?", (imported["id"],)) == 0
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_idempotency WHERE idempotency_key LIKE 'persisted-event-conflict-%'") == 0


def test_event_collision_from_another_principal_is_generic_409(client):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "other principal event source")["mission"]
    imported = _copy_mission(source, "other_principal_001")

    other = TestClient(client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50997))
    other.cookies.set("jarvis_session", "owner-r1-session-token")
    put_session_for_tests("owner-r1-session-token", "owner_r1", "csrf-owner-r1-token")
    put_grant_for_tests(Grant(
        id="grant-owner-r1-write", principal="owner_r1", connector="mission_sim",
        resource_ids=frozenset({"mission:read", "mission:write"}),
        domain_ids=frozenset({"dom_synthetic_a"}),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))

    response = _import(other, "csrf-owner-r1-token", [imported], "cross-principal-event-conflict")

    assert response.status_code == 409
    assert response.json() == {"detail": "conflito de identidade na importação"}
    assert source["id"] not in response.text
    assert source["events"][0]["id"] not in response.text
    assert _count(client.database_path, "SELECT COUNT(*) FROM missions WHERE id=?", (imported["id"],)) == 0


def test_import_internal_key_can_match_a_user_create_key_without_collision(client):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "namespace collision source")
    imported = _copy_mission(source["mission"], "namespace_collision_001",
                             event_ids=("event_r2_namespace_collision_01",))
    imported["id"] = "mission_audit_internal_key_collision"
    import_key = "audit-import-keyspace"
    internal_key = f"{import_key}:{imported['id']}"

    prior_create = client.post(
        "/real/missions",
        headers=_headers(csrf),
        json={
            "title": "chave criada pelo usuário",
            "domain_id": "dom_synthetic_a",
            "idempotency_key": internal_key,
        },
    )
    assert prior_create.status_code == 201, prior_create.text

    imported_response = _import(client, csrf, [imported], import_key)

    assert imported_response.status_code == 200, imported_response.text
    assert imported_response.json()["accepted"] == [imported["id"]]
    assert _count(
        client.database_path,
        "SELECT COUNT(*) FROM missions WHERE id IN (?, ?)",
        (prior_create.json()["mission"]["id"], imported["id"]),
    ) == 2
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_create_and_import_share_textual_key_without_cross_operation_replay(client):
    csrf = login(client)
    mission_grants(client, csrf)
    shared_key = "same-text-different-operation-r2"
    created = client.post(
        "/real/missions",
        headers=_headers(csrf),
        json={"title": "criação", "domain_id": "dom_synthetic_a", "idempotency_key": shared_key},
    )
    assert created.status_code == 201, created.text

    imported = _copy_mission(
        created.json()["mission"], "cross_operation_import_001",
        event_ids=("event_cross_operation_import_01",),
    )
    imported_response = _import(client, csrf, [imported], shared_key)
    assert imported_response.status_code == 200, imported_response.text
    assert imported_response.json()["accepted"] == [imported["id"]]

    create_replay = client.post(
        "/real/missions",
        headers=_headers(csrf),
        json={"title": "criação", "domain_id": "dom_synthetic_a", "idempotency_key": shared_key},
    )
    import_replay = _import(client, csrf, [imported], shared_key)
    assert create_replay.status_code == 201
    assert create_replay.json()["replayed"] is True
    assert create_replay.json()["mission"]["id"] == created.json()["mission"]["id"]
    assert import_replay.status_code == 200
    assert import_replay.json()["replayed"] is True
    assert import_replay.json()["accepted"] == [imported["id"]]

    changed_create = client.post(
        "/real/missions",
        headers=_headers(csrf),
        json={"title": "outro corpo", "domain_id": "dom_synthetic_a", "idempotency_key": shared_key},
    )
    changed_import_document = copy.deepcopy(imported)
    changed_import_document["title"] = "corpo diferente na mesma operação"
    changed_import = _import(client, csrf, [changed_import_document], shared_key)
    assert changed_create.status_code == 409
    assert changed_import.status_code == 409
    assert shared_key not in changed_create.text + changed_import.text

    with sqlite3.connect(client.database_path) as connection:
        operations = connection.execute(
            "SELECT operation FROM mission_idempotency WHERE owner='owner' AND idempotency_key=? "
            "ORDER BY operation",
            (shared_key,),
        ).fetchall()
    assert [row[0] for row in operations] == ["mission.create", "mission.import"]


def test_concurrent_same_create_key_has_one_record_and_one_replay(client):
    csrf = login(client)
    mission_grants(client, csrf)
    key = "concurrent-create-shared-key-r2"
    barrier = Barrier(2)

    def send():
        barrier.wait(timeout=10)
        return client.post(
            "/real/missions",
            headers=_headers(csrf),
            json={"title": "concorrência", "domain_id": "dom_synthetic_a", "idempotency_key": key},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result(timeout=15) for future in (pool.submit(send), pool.submit(send))]

    assert [response.status_code for response in responses] == [201, 201]
    bodies = [response.json() for response in responses]
    assert sorted(body["replayed"] for body in bodies) == [False, True]
    assert len({body["mission"]["id"] for body in bodies}) == 1
    assert _count(
        client.database_path,
        "SELECT COUNT(*) FROM mission_idempotency WHERE owner='owner' AND operation='mission.create' AND idempotency_key=?",
        (key,),
    ) == 1
    assert _count(client.database_path, "SELECT COUNT(*) FROM missions") == 1


def test_concurrent_create_and_import_can_share_a_textual_key(client):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "concorrência entre operações", "cross-operation-source-r2")
    imported = _copy_mission(
        source["mission"], "concurrent_cross_operation_001",
        event_ids=("event_concurrent_cross_operation_01",),
    )
    key = "concurrent-cross-operation-key-r2"
    barrier = Barrier(2)

    def send_create():
        barrier.wait(timeout=10)
        return client.post(
            "/real/missions",
            headers=_headers(csrf),
            json={"title": "concorrência criação", "domain_id": "dom_synthetic_a", "idempotency_key": key},
        )

    def send_import():
        barrier.wait(timeout=10)
        return _import(client, csrf, [imported], key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        create_future = pool.submit(send_create)
        import_future = pool.submit(send_import)
        created = create_future.result(timeout=15)
        imported_response = import_future.result(timeout=15)

    assert created.status_code == 201, created.text
    assert imported_response.status_code == 200, imported_response.text
    assert imported_response.json()["accepted"] == [imported["id"]]
    assert _count(
        client.database_path,
        "SELECT COUNT(*) FROM mission_idempotency WHERE owner='owner' AND idempotency_key=? "
        "AND operation IN ('mission.create', 'mission.import')",
        (key,),
    ) == 2
    with sqlite3.connect(client.database_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_unknown_database_idempotency_constraint_is_not_reclassified_as_conflict(client):
    store = client.app.state.memory_store
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        with store.transaction() as connection:
            _store_idempotency(
                connection,
                "owner",
                "mission.operation.not_registered",
                "unknown-operation-key-r2",
                "mission_unknown_operation_001",
                "c" * 64,
            )

    assert _count(
        client.database_path,
        "SELECT COUNT(*) FROM mission_idempotency WHERE owner='owner' AND idempotency_key=?",
        ("unknown-operation-key-r2",),
    ) == 0


def test_unresolved_legacy_key_fails_closed_and_remains_owner_scoped(tmp_path, monkeypatch):
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    for migration in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if migration.stem == "0013_mission_idempotency_scopes":
            continue
        copyfile(migration, old_migrations / migration.name)

    database_path = tmp_path / "legacy" / "memory.sqlite3"
    SQLiteMemoryStore(database_path, migrations_dir=old_migrations).initialize()
    key = "legacy-key-owner-scoped-r2"
    legacy_row = ("owner", key, "mission_legacy_record_001", "b" * 64, None)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO mission_idempotency(owner, idempotency_key, mission_id, body_sha256, result_json) "
            "VALUES (?, ?, ?, ?, ?)",
            legacy_row,
        )

    monkeypatch.setenv("JARVIS_LOCAL_PASSPHRASE", PASSPHRASE)
    app = create_app(LocalServerConfig(), database_path=database_path)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50999)) as migrated:
        migrated.database_path = database_path
        csrf = login(migrated)
        mission_grants(migrated, csrf)
        create_conflict = migrated.post(
            "/real/missions",
            headers=_headers(csrf),
            json={"title": "não reinterpretar", "domain_id": "dom_synthetic_a", "idempotency_key": key},
        )
        assert create_conflict.status_code == 409
        assert create_conflict.json() == {"detail": "chave de idempotência legada exige reconciliação"}
        assert key not in create_conflict.text

        source = create(migrated, csrf, "fonte para teste legado", "legacy-source-create-r2")
        document = _copy_mission(
            source["mission"], "legacy_import_probe_001",
            event_ids=("event_legacy_import_probe_01",),
        )
        import_conflict = _import(migrated, csrf, [document], key)
        assert import_conflict.status_code == 409
        assert import_conflict.json() == {"detail": "chave de idempotência legada exige reconciliação"}
        assert document["id"] not in import_conflict.text
        assert _count(database_path, "SELECT COUNT(*) FROM missions WHERE id=?", (document["id"],)) == 0

        other = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51002))
        other.cookies.set("jarvis_session", "owner-r2-legacy-session")
        put_session_for_tests("owner-r2-legacy-session", "owner_r2", "csrf-owner-r2-legacy")
        put_grant_for_tests(Grant(
            id="grant-owner-r2-legacy-write", principal="owner_r2", connector="mission_sim",
            resource_ids=frozenset({"mission:write"}), domain_ids=frozenset({"dom_synthetic_a"}),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        other_create = create(other, "csrf-owner-r2-legacy", "same key in other principal", key)
        assert other_create["mission"]["title"] == "same key in other principal"

    with sqlite3.connect(database_path) as connection:
        migrated_row = connection.execute(
            "SELECT operation, owner, idempotency_key, mission_id, body_sha256, result_json "
            "FROM mission_idempotency WHERE owner=? AND idempotency_key=?",
            (legacy_row[0], legacy_row[1]),
        ).fetchone()
        assert migrated_row == ("legacy_unresolved", *legacy_row)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_import_response_lost_after_commit_replays_after_restart(client, monkeypatch):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "timeout replay source")["mission"]
    imported = _copy_mission(source, "timeout_restart_001", event_ids=("event_timeout_restart_01",))
    key = "timeout-replay-after-restart"
    original_import = MissionRepository.import_valid

    def commit_then_drop_response(repository, owner, documents, idempotency_key):
        result = original_import(repository, owner, documents, idempotency_key)
        if idempotency_key == key:
            raise httpx.ReadTimeout("simulated response loss after SQLite commit")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(MissionRepository, "import_valid", commit_then_drop_response)
        with pytest.raises(httpx.ReadTimeout):
            _import(client, csrf, [imported], key)

    assert _count(client.database_path, "SELECT COUNT(*) FROM missions WHERE id=?", (imported["id"],)) == 1
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_idempotency WHERE owner='owner' AND idempotency_key=?", (key,)) == 1
    events_before_restart = _count(client.database_path, "SELECT COUNT(*) FROM mission_events")

    database = client.database_path
    reset_state()
    restarted_app = create_app(LocalServerConfig(), database_path=database)
    with TestClient(restarted_app, base_url="http://127.0.0.1", client=("127.0.0.1", 50998)) as restarted:
        restarted_csrf = login(restarted)
        mission_grants(restarted, restarted_csrf)
        replay = _import(restarted, restarted_csrf, [imported], key)

    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["accepted"] == [imported["id"]]
    assert _count(database, "SELECT COUNT(*) FROM mission_events") == events_before_restart


def test_concurrent_imports_sharing_event_id_have_one_winner_and_one_409(client):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "concurrent event collision source")["mission"]
    documents = [
        _copy_mission(source, "concurrent_event_a01", event_ids=("event_concurrent_shared_01",)),
        _copy_mission(source, "concurrent_event_b01", event_ids=("event_concurrent_shared_01",)),
    ]
    barrier = Barrier(2)

    def send(index: int):
        barrier.wait(timeout=10)
        return _import(client, csrf, [documents[index]], f"concurrent-event-import-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result(timeout=15) for future in [pool.submit(send, 0), pool.submit(send, 1)]]

    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json() == {"detail": "conflito de identidade na importação"}
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_events WHERE id='event_concurrent_shared_01'") == 1
    assert _count(client.database_path, "SELECT COUNT(*) FROM missions WHERE id IN (?, ?)", tuple(doc["id"] for doc in documents)) == 1


def test_concurrent_same_import_key_is_replayed_once(client):
    csrf = login(client)
    mission_grants(client, csrf)
    source = create(client, csrf, "concurrent idempotency source")["mission"]
    imported = _copy_mission(source, "concurrent_replay_001", event_ids=("event_concurrent_replay_01",))
    key = "concurrent-identical-import"
    barrier = Barrier(2)

    def send():
        barrier.wait(timeout=10)
        return _import(client, csrf, [imported], key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result(timeout=15) for future in [pool.submit(send), pool.submit(send)]]

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["replayed"] for response in responses) == [False, True]
    assert all(response.json()["accepted"] == [imported["id"]] for response in responses)
    assert _count(client.database_path, "SELECT COUNT(*) FROM missions WHERE id=?", (imported["id"],)) == 1
    assert _count(client.database_path, "SELECT COUNT(*) FROM mission_events WHERE id='event_concurrent_replay_01'") == 1
