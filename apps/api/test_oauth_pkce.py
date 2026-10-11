from __future__ import annotations

import pytest

from external_connectors import GMAIL_READONLY_SCOPE, ConnectorUnavailable, read_gmail_messages, read_google_calendar_events
from oauth_pkce import authorization_url, exchange_authorization_code, generate_pkce, store_refresh_token, MemoryTokenStore


def test_pkce_stays_local_until_explicit_consent(monkeypatch):
    monkeypatch.delenv("JARVIS_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    with pytest.raises(ConnectorUnavailable):
        authorization_url(scope=GMAIL_READONLY_SCOPE, state="s" * 16, challenge="c" * 43)
    monkeypatch.setenv("JARVIS_GOOGLE_OAUTH_CLIENT_ID", "synthetic-oauth-client")
    pair = generate_pkce()
    url = authorization_url(scope=GMAIL_READONLY_SCOPE, state="s" * 16, challenge=pair.challenge)
    assert "code_challenge_method=S256" in url
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly" in url
    assert "redirect_uri=jarvis%3A%2F%2Foauth%2Fcallback" in url
    called: list[dict[str, str]] = []

    def transport(payload: dict[str, str]) -> dict[str, str]:
        called.append(payload)
        return {"refresh_token": "synthetic-refresh", "access_token": "synthetic-access"}

    with pytest.raises(ConnectorUnavailable):
        exchange_authorization_code(code="code", verifier=pair.verifier, transport=transport, consent=False)
    assert called == []
    tokens = exchange_authorization_code(code="code", verifier=pair.verifier, transport=transport, consent=True)
    assert called[0]["code_verifier"] == pair.verifier
    store = MemoryTokenStore()
    with pytest.raises(ConnectorUnavailable):
        store_refresh_token(store, "gmail", tokens["refresh_token"], consent=False)
    assert store.get("gmail") is None
    store_refresh_token(store, "gmail", tokens["refresh_token"], consent=True)
    assert store.get("gmail") == "synthetic-refresh"
    with pytest.raises(ConnectorUnavailable):
        read_gmail_messages()
    with pytest.raises(ConnectorUnavailable):
        read_google_calendar_events()
