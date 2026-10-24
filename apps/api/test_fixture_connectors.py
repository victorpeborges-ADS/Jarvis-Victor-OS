from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from calendar_simulator import CALENDAR_SOURCE, CalendarProvider, SimulatedCalendarEvent
from fixture_connectors import (
    APPROVAL_STEPS,
    CONNECTOR_KINDS,
    MAX_ITEMS,
    ContentEffect,
    ConnectorReadResult,
    FixtureCache,
    ResponseLimits,
    RevocationRegistry,
    begin_real_connector,
    classify_target,
    effects_from_read,
    effects_from_search,
    page_fixture,
    read_fixture,
    read_named_fixture,
    real_connector_approvals,
    project_simulated_calendar,
    start_mcp_stdio,
    sync_fixture,
    unified_search,
    RealConnectorBlocked,
)

OBSERVED = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
CURRENT = (
    ("gmail", "gmail_current"),
    ("calendar", "calendar_current"),
    ("drive", "drive_current"),
    ("github", "github_current"),
    ("mcp", "mcp_current"),
)
TARGETS = (
    ("http://127.0.0.1/", "loopback_refused"),
    ("http://127.0.0.2/admin", "loopback_refused"),
    ("http://localhost/admin", "loopback_refused"),
    ("http://foo.localhost/admin", "loopback_refused"),
    ("http://[::1]/", "loopback_refused"),
    ("http://[::ffff:127.0.0.1]/", "loopback_refused"),
    ("http://[64:ff9b::7f00:1]/", "loopback_refused"),
    ("http://2130706433/", "loopback_refused"),
    ("http://0177.0.0.1/", "loopback_refused"),
    ("http://0x7f000001/", "loopback_refused"),
    ("http://127.1/", "loopback_refused"),
    ("http://169.254.169.254/computeMetadata/v1/", "metadata_refused"),
    ("http://metadata.google.internal/", "metadata_refused"),
    ("http://metadata.google.com/", "metadata_refused"),
    ("http://[fd00:ec2::254]/", "metadata_refused"),
    ("http://100.100.100.200/", "metadata_refused"),
    ("http://169.254.10.1/", "link_local_refused"),
    ("http://[fe80::1]/", "link_local_refused"),
    ("http://10.1.2.3/", "local_or_private_refused"),
    ("http://192.168.0.9/", "local_or_private_refused"),
    ("http://172.16.0.4/", "local_or_private_refused"),
    ("http://0.0.0.0/", "local_or_private_refused"),
    ("http://100.64.0.1/", "local_or_private_refused"),
    ("http://printer.local/", "local_or_private_refused"),
    ("https://gmail.googleapis.com/gmail/v1/users/me/messages", "dns_refused"),
    ("https://api.github.com/repos/synthetic/notes", "dns_refused"),
    ("http://8.8.8.8/", "egress_disabled"),
    ("http://[2606:4700:4700::1111]/", "egress_disabled"),
    ("file:///etc/passwd", "unsupported_target"),
    ("http://sintetico:sintetico@example.com/", "unsupported_target"),
    ("gopher://example.com/", "unsupported_target"),
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("rede recusada")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "getnameinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


def _read(kind: str, name: str, **kwargs: object) -> ConnectorReadResult:
    return read_named_fixture(kind, name, observed_at=OBSERVED, **kwargs)  # type: ignore[arg-type]


def _dump(value: object) -> str:
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def test_module_has_no_network_api() -> None:
    source = Path(__file__).with_name("fixture_connectors.py").read_text(encoding="utf-8")
    for token in ("getaddrinfo", "urlopen", "httpx", "create_connection", "import socket", "requests.", "urllib.request"):
        assert token not in source


def test_current_fixtures_share_one_contract() -> None:
    reads = []
    for kind, name in CURRENT:
        result = _read(kind, name)
        reads.append(result)
        assert result.identity.kind == kind
        assert result.identity.mode == "fake_fixture"
        assert result.identity.connector_id == f"fixture:{kind}"
        assert result.identity.account_ref == "synthetic"
        assert result.identity.scope
        assert result.origin.synthetic is True
        assert result.origin.trust == "untrusted_external"
        assert result.origin.origin == f"synthetic-fixture:{name}"
        assert result.collected_at == OBSERVED
        assert result.freshness == "current"
        assert result.presented_as_current is True
        assert result.complete is True
        assert result.refusal is None
        assert result.network_attempted is False
        assert result.limits.dns == "do_not_resolve"
        assert result.limits.redirects == "refuse"
        assert result.limits.egress == "disabled"
        assert result.limits.max_items == 20
        assert result.limits.max_response_bytes == 2048
        assert result.limits.timeout_ms == 1000
        assert result.freshness_rule.revoked_is_not_current is True
        assert result.freshness_rule.stale_is_not_current is True
        assert result.items
        assert effects_from_read(result) == ContentEffect()
        again = _read(kind, name)
        assert again == result
        assert ConnectorReadResult.model_validate(result.model_dump()) == result
    assert _read("calendar", "calendar_current").origin.gate_d_source_id == CALENDAR_SOURCE.id
    found = unified_search(reads, "", observed_at=OBSERVED)
    assert found.complete is True
    assert len(found.current_items) == 5
    assert effects_from_search(found) == ContentEffect()
    assert [hit.kind for hit in found.current_items] == ["calendar", "drive", "github", "gmail", "mcp"]
    nota = unified_search(reads, "CORREIO", observed_at=OBSERVED)
    assert [hit.external_id for hit in nota.current_items] == ["m-1"]
    assert nota.complete is True
    reuniao = unified_search(reads, "reunião", observed_at=OBSERVED)
    assert [hit.external_id for hit in reuniao.current_items] == ["evt-sintetico-1"]
    empty = unified_search(reads, "inexistente", observed_at=OBSERVED)
    assert empty.current_items == ()
    assert empty.complete is True


def test_malformed_responses_are_not_current() -> None:
    broken = _read("gmail", "malformed")
    extra = _read("gmail", "malformed_extra")
    item = _read("gmail", "malformed_item")
    for result in (broken, extra, item):
        assert result.refusal is not None
        assert result.refusal.code == "malformed"
        assert result.freshness == "refused"
        assert result.items == ()
        assert result.presented_as_current is False
        assert result.complete is False
        assert result.network_attempted is False
    assert "injected" not in _dump(extra)
    assert "sem assunto" not in _dump(item)


def test_revoked_and_stale_sources_are_not_presented_as_current() -> None:
    revoked = _read("gmail", "revoked")
    stale = _read("drive", "stale")
    current = _read("github", "github_current")
    assert revoked.freshness == "revoked"
    assert revoked.presented_as_current is False
    assert revoked.complete is False
    assert revoked.items == ()
    assert revoked.withheld_count == 1
    assert stale.freshness == "stale"
    assert stale.presented_as_current is False
    assert stale.items == ()
    found = unified_search((current, revoked, stale), "", observed_at=OBSERVED)
    assert found.complete is False
    assert [hit.external_id for hit in found.current_items] == ["gh-1"]
    dumped = _dump(found)
    assert "Mensagem revogada" not in dumped
    assert "Arquivo antigo" not in dumped
    marks = {(mark.fixture_id, mark.freshness, mark.presented_as_current) for mark in found.sources}
    assert ("revoked", "revoked", False) in marks
    assert ("stale", "stale", False) in marks
    assert ("github_current", "current", True) in marks


def test_registry_revocation_overrides_a_fresh_fixture() -> None:
    registry = RevocationRegistry()
    registry.revoke("fixture:gmail")
    result = _read("gmail", "gmail_current", registry=registry)
    assert result.freshness == "revoked"
    assert result.presented_as_current is False
    assert result.items == ()
    assert "Nota sintética" not in _dump(result)
    with pytest.raises(ValueError):
        registry.revoke("gmail-real")


def test_timeout_does_not_wait_or_return_items() -> None:
    started = time.perf_counter()
    result = _read("github", "timeout")
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25
    assert result.refusal is not None
    assert result.refusal.code == "timeout"
    assert result.items == ()
    assert result.presented_as_current is False
    assert "marcador-timeout" not in _dump(result)
    deadline = _read("gmail", "gmail_current", deadline=OBSERVED - timedelta(seconds=1))
    assert deadline.refusal is not None
    assert deadline.refusal.code == "timeout"
    assert "Nota sintética" not in _dump(deadline)


def test_redirect_is_refused_before_the_location_is_used() -> None:
    decision = classify_target("http://127.0.0.1/marcador-redirect-alvo", redirected=True)
    assert decision.reason == "redirect_refused"
    assert decision.allowed is False
    assert decision.redirect_followed is False
    assert decision.network_attempted is False
    assert decision.dns_lookup is False
    assert "marcador-redirect-alvo" not in _dump(decision)
    result = _read("drive", "redirect")
    assert result.refusal is not None
    assert result.refusal.code == "redirect_refused"
    assert result.egress is not None
    assert result.egress.redirect_followed is False
    assert result.items == ()
    dumped = _dump(result)
    assert "marcador-redirect" not in dumped
    assert "127.0.0.1" not in dumped
    public = classify_target("https://api.github.com/repos/synthetic/notes", redirected=True)
    assert public.reason == "redirect_refused"
    assert public.dns_lookup is False


@pytest.mark.parametrize(("url", "reason"), TARGETS)
def test_local_and_remote_targets_are_refused_before_network(url: str, reason: str, tmp_path: Path) -> None:
    decision = classify_target(url)
    assert decision.allowed is False
    assert decision.reason == reason
    assert decision.network_attempted is False
    assert decision.dns_lookup is False
    assert decision.redirect_followed is False
    payload = {
        "fixture_id": "case_url",
        "connector": "gmail",
        "source_claimed_at": "2026-10-17T11:50:00Z",
        "fetch_url": url,
        "items": [
            {
                "kind": "gmail",
                "external_id": "m-url",
                "subject": "nao ler",
                "snippet": "marcador-nao-ler",
            }
        ],
    }
    path = tmp_path / "case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = read_fixture("gmail", path, observed_at=OBSERVED, root=tmp_path)
    assert result.refusal is not None
    assert result.refusal.code == reason
    assert result.items == ()
    assert result.presented_as_current is False
    assert result.complete is False
    assert result.network_attempted is False
    assert result.limits.egress == "disabled"
    assert "marcador-nao-ler" not in _dump(result)


def test_packaged_local_url_fixture_is_loopback() -> None:
    result = _read("gmail", "local_url")
    assert result.refusal is not None
    assert result.refusal.code == "loopback_refused"
    assert result.egress is not None
    assert result.egress.dns_lookup is False
    dumped = _dump(result)
    assert "marcador-local" not in dumped
    assert "meta-data" not in dumped


def test_duplicate_collapses_to_one_current_item() -> None:
    result = _read("gmail", "duplicate")
    assert result.presented_as_current is True
    assert result.complete is True
    assert result.duplicate_count == 1
    assert len(result.items) == 1
    assert result.items[0].external_id == "m-dup"
    assert result.items[0].subject == "primeiro"  # type: ignore[attr-defined]
    assert "segundo" not in _dump(result)
    first = _read("gmail", "gmail_current")
    second = _read("gmail", "gmail_current")
    found = unified_search((first, second), "", observed_at=OBSERVED)
    assert found.complete is True
    assert found.duplicate_count == 1
    assert len(found.current_items) == 1


def test_large_result_is_not_complete() -> None:
    result = _read("gmail", "large")
    assert result.refusal is not None
    assert result.refusal.code == "response_too_large"
    assert result.complete is False
    assert result.presented_as_current is False
    assert result.items == ()
    assert result.withheld_count == 0
    assert "marcador-grande-sintetico" not in _dump(result)
    found = unified_search((result, _read("drive", "drive_current")), "", observed_at=OBSERVED)
    assert found.complete is False
    assert [hit.kind for hit in found.current_items] == ["drive"]


def test_item_count_above_the_limit_is_not_complete(tmp_path: Path) -> None:
    items = [
        {"kind": "gmail", "external_id": f"m{index:02d}", "subject": "a", "snippet": "b"}
        for index in range(MAX_ITEMS + 1)
    ]
    payload = {
        "fixture_id": "muitos",
        "connector": "gmail",
        "source_claimed_at": "2026-10-17T11:50:00Z",
        "items": items,
    }
    path = tmp_path / "muitos.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = read_fixture("gmail", path, observed_at=OBSERVED, root=tmp_path)
    assert result.refusal is not None
    assert result.refusal.code == "response_too_large"
    assert result.withheld_count == MAX_ITEMS + 1
    assert result.items == ()
    assert result.complete is False


def test_external_content_does_not_grant_or_open_tools() -> None:
    mail = _read("gmail", "untrusted_gmail")
    assert mail.presented_as_current is True
    assert "send_email" in mail.items[0].snippet  # type: ignore[attr-defined]
    assert effects_from_read(mail) == ContentEffect()
    found = unified_search((mail,), "administrador", observed_at=OBSERVED)
    assert len(found.current_items) == 1
    assert found.current_items[0].trust == "untrusted_external"
    assert effects_from_search(found) == ContentEffect()
    malicious = _read("mcp", "mcp_malicious")
    assert malicious.refusal is not None
    assert malicious.refusal.code == "mcp_not_allowlisted"
    assert malicious.items == ()
    assert "send_email" not in _dump(malicious)
    assert effects_from_read(malicious) == ContentEffect()
    missing = _read("mcp", "mcp_missing_schema")
    assert missing.refusal is not None
    assert missing.refusal.code == "malformed"
    assert missing.items == ()
    listed = _read("mcp", "mcp_current")
    assert listed.items[0].read_only_annotation is False  # type: ignore[attr-defined]
    assert listed.items[0].tool_name == "fixture.echo"  # type: ignore[attr-defined]
    assert effects_from_read(listed).tools_opened == ()
    with pytest.raises(ValidationError):
        ContentEffect(grants=("admin",))
    with pytest.raises(ValidationError):
        ResponseLimits(max_items=21)  # type: ignore[arg-type]


def test_future_claim_is_not_current(tmp_path: Path) -> None:
    payload = {
        "fixture_id": "futuro",
        "connector": "gmail",
        "source_claimed_at": "2026-10-17T13:00:00Z",
        "items": [{"kind": "gmail", "external_id": "m-futuro", "subject": "amanha", "snippet": "cedo"}],
    }
    path = tmp_path / "futuro.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = read_fixture("gmail", path, observed_at=OBSERVED, root=tmp_path)
    assert result.freshness == "stale"
    assert result.presented_as_current is False
    assert result.items == ()


def test_kind_mismatch_drops_the_other_connector() -> None:
    result = _read("drive", "gmail_current")
    assert result.identity.kind == "drive"
    assert result.refusal is not None
    assert result.refusal.code == "kind_mismatch"
    assert result.items == ()
    assert "Nota sintética" not in _dump(result)


def test_path_escape_and_symlink_are_not_read(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("marcador-fora-da-raiz", encoding="utf-8")
    escaped = read_fixture("gmail", outside, observed_at=OBSERVED, root=root)
    assert escaped.refusal is not None
    assert escaped.refusal.code == "path_refused"
    assert "marcador-fora-da-raiz" not in _dump(escaped)
    target = tmp_path / "secret.json"
    target.write_text("marcador-symlink", encoding="utf-8")
    link = root / "link.json"
    link.symlink_to(target)
    linked = read_fixture("gmail", link, observed_at=OBSERVED, root=root)
    assert linked.refusal is not None
    assert linked.refusal.code == "path_refused"
    assert "marcador-symlink" not in _dump(linked)


def test_all_day_calendar_fixture_is_rejected() -> None:
    result = _read("calendar", "calendar_all_day")
    assert result.refusal is not None
    assert result.refusal.code == "malformed"
    assert result.items == ()
    assert result.origin.gate_d_source_id is None
    assert "Dia inteiro" not in _dump(result)


def test_simulated_calendar_projection_stays_local() -> None:
    provider = CalendarProvider()
    provider.publish_event(
        SimulatedCalendarEvent(
            calendar_id="sim_calendar_a",
            event_id="evt-proj-1",
            summary="Projeção sintética",
            start_at=datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 18, 15, 30, tzinfo=timezone.utc),
            time_zone="America/Sao_Paulo",
            updated_at=OBSERVED,
        )
    )
    result = project_simulated_calendar(provider, "sim_calendar_a", observed_at=OBSERVED)
    assert result.identity.mode == "calendar_sim"
    assert result.identity.connector_id == "calendar_sim:synthetic-primary"
    assert result.identity.account_ref == "synthetic"
    assert result.origin.gate_d_source_id == CALENDAR_SOURCE.id
    assert result.origin.gate_d_source_id == "src_calendar_sim_google"
    assert result.presented_as_current is True
    assert result.network_attempted is False
    projected = [item for item in result.items if item.external_id == "evt-proj-1"]
    assert len(projected) == 1
    assert projected[0].summary == "Projeção sintética"  # type: ignore[attr-defined]
    assert projected[0].all_day is False  # type: ignore[attr-defined]
    missing = project_simulated_calendar(provider, "sim_calendar_z", observed_at=OBSERVED)
    assert missing.refusal is not None
    assert missing.refusal.code == "provider_unavailable"
    assert missing.items == ()
    registry = RevocationRegistry()
    registry.revoke("calendar_sim:synthetic-primary")
    revoked = project_simulated_calendar(provider, "sim_calendar_a", observed_at=OBSERVED, registry=registry)
    assert revoked.freshness == "revoked"
    assert revoked.items == ()
    assert "Projeção sintética" not in _dump(revoked)


def test_real_connectors_stay_blocked_and_unstarted() -> None:
    plans = real_connector_approvals()
    assert tuple(plan.kind for plan in plans) == CONNECTOR_KINDS
    before = [plan.model_dump() for plan in plans]
    for plan in plans:
        assert plan.state == "BLOCKED"
        assert plan.started is False
        assert tuple(step.step for step in plan.steps) == APPROVAL_STEPS
        assert all(step.state == "BLOCKED" and step.started is False and step.detail for step in plan.steps)
    with pytest.raises(RealConnectorBlocked) as caught:
        begin_real_connector("gmail")
    assert caught.value.kind == "gmail"
    assert caught.value.state == "BLOCKED"
    assert caught.value.started is False
    assert [plan.model_dump() for plan in real_connector_approvals()] == before
    with pytest.raises(ValueError):
        begin_real_connector("imap")


def test_long_target_is_refused_without_resolution() -> None:
    decision = classify_target("http://" + ("a" * 3000) + ".example")
    assert decision.reason == "unsupported_target"
    assert decision.dns_lookup is False
    assert decision.network_attempted is False


def _gmail_page(tmp_path: Path, items: list[dict[str, str]], **extra: object) -> ConnectorReadResult:
    payload = {
        "fixture_id": "gmail_pages",
        "connector": "gmail",
        "source_claimed_at": "2026-10-17T11:50:00Z",
        "items": items,
    }
    payload.update(extra)
    path = tmp_path / "gmail_pages.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return read_fixture("gmail", path, observed_at=OBSERVED, root=tmp_path)


def test_pages_and_sync_do_not_repeat_or_look_complete(tmp_path: Path) -> None:
    items = [
        {"kind": "gmail", "external_id": f"m-{index}", "subject": "Nota", "snippet": f"Texto {index}"}
        for index in (1, 2, 3)
    ]
    result = _gmail_page(tmp_path, items)
    first = page_fixture(result, page_size=2)
    assert first.complete is False
    assert first.next_cursor == "m-2"
    assert [item.external_id for item in first.items] == ["m-1", "m-2"]
    assert first.network_attempted is False
    second = page_fixture(result, page_size=2, cursor=first.next_cursor)
    assert second.complete is True
    assert [item.external_id for item in second.items] == ["m-3"]
    delta = sync_fixture(result, since="m-1", page_size=1)
    assert delta.complete is False
    assert [item.external_id for item in delta.items] == ["m-2"]
    assert "m-1" not in [item.external_id for item in delta.items]


def test_invalid_token_blocks_the_fixture_without_network(tmp_path: Path) -> None:
    result = _gmail_page(
        tmp_path,
        [{"kind": "gmail", "external_id": "m-1", "subject": "Nota", "snippet": "Texto"}],
        token_state="invalid",
    )
    assert result.freshness == "refused"
    assert result.complete is False
    assert result.items == ()
    assert result.refusal is not None and result.refusal.code == "token_invalid"
    assert result.network_attempted is False


def test_missing_mcp_schema_blocks_the_whole_read(tmp_path: Path) -> None:
    path = tmp_path / "mcp_missing.json"
    path.write_text(json.dumps({
        "fixture_id": "mcp_missing_schema",
        "connector": "mcp",
        "source_claimed_at": "2026-10-17T11:50:00Z",
        "items": [{
            "kind": "mcp",
            "external_id": "tool-1",
            "tool_name": "fixture.echo",
            "read_only_annotation": True,
            "description": "sem versao",
        }],
    }), encoding="utf-8")
    result = read_fixture("mcp", path, observed_at=OBSERVED, root=tmp_path)
    assert result.complete is False
    assert result.items == ()
    assert result.refusal is not None and result.refusal.code == "malformed"


def test_removal_and_revocation_drop_the_cached_context(tmp_path: Path) -> None:
    full = tmp_path / "drive_full.json"
    full.write_text(json.dumps({
        "fixture_id": "drive_full",
        "connector": "drive",
        "source_claimed_at": "2026-10-17T11:50:00Z",
        "items": [
            {"kind": "drive", "external_id": "file-1", "name": "Um.txt", "mime_type": "text/plain"},
            {"kind": "drive", "external_id": "file-2", "name": "Dois.txt", "mime_type": "text/plain"},
        ],
    }), encoding="utf-8")
    cache = FixtureCache()
    first = read_fixture("drive", full, observed_at=OBSERVED, root=tmp_path)
    cache.remember(first)
    assert cache.external_ids("fixture:drive") == ("file-1", "file-2")
    reduced = tmp_path / "drive_reduced.json"
    reduced.write_text(json.dumps({
        "fixture_id": "drive_reduced",
        "connector": "drive",
        "source_claimed_at": "2026-10-17T11:50:00Z",
        "items": [
            {"kind": "drive", "external_id": "file-2", "name": "Dois.txt", "mime_type": "text/plain"},
        ],
    }), encoding="utf-8")
    cache.remember(read_fixture("drive", reduced, observed_at=OBSERVED, root=tmp_path))
    assert cache.external_ids("fixture:drive") == ("file-2",)
    registry = RevocationRegistry()
    registry.revoke("fixture:drive")
    revoked = read_fixture("drive", reduced, observed_at=OBSERVED, root=tmp_path, registry=registry)
    cache.remember(revoked)
    assert revoked.freshness == "revoked"
    assert revoked.complete is False
    assert cache.external_ids("fixture:drive") == ()


def test_mcp_stdio_is_not_started() -> None:
    source = Path(__file__).with_name("fixture_connectors.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    with pytest.raises(RealConnectorBlocked) as caught:
        start_mcp_stdio()
    assert caught.value.kind == "mcp"
    assert caught.value.started is False
