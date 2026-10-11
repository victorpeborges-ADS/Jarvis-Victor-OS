"""OAuth desktop PKCE para Gmail e Calendar, somente leitura.

Nenhuma função abre socket, navegador ou a rede. O transporte de token é injetado
e os testes usam um dublê. Sem client ID ou sem consentimento, a chamada falha.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlencode

from external_connectors import (
    CALENDAR_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    ConnectorUnavailable,
    oauth_client_id_configured,
)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "jarvis://oauth/callback"


class TokenStore(Protocol):
    def put(self, account: str, secret: str) -> None: ...

    def get(self, account: str) -> str | None: ...


class MemoryTokenStore:
    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def put(self, account: str, secret: str) -> None:
        if not account or not secret:
            raise ValueError("token vazio")
        self._items[account] = secret

    def get(self, account: str) -> str | None:
        return self._items.get(account)


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


def generate_pkce() -> PkcePair:
    verifier = secrets.token_urlsafe(64)
    verifier = verifier[:128]
    if len(verifier) < 43:
        raise RuntimeError("verifier PKCE curto")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return PkcePair(verifier, challenge)


def authorization_url(*, scope: str, state: str, challenge: str) -> str:
    if not oauth_client_id_configured():
        raise ConnectorUnavailable("client ID ausente")
    if scope not in {GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE}:
        raise ConnectorUnavailable("escopo fora da leitura")
    if not state or len(state) < 16 or not challenge:
        raise ConnectorUnavailable("estado PKCE incompleto")
    import os
    client_id = os.environ["JARVIS_GOOGLE_OAUTH_CLIENT_ID"].strip()
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def store_refresh_token(store: TokenStore, account: str, refresh_token: str, *, consent: bool) -> None:
    if not consent:
        raise ConnectorUnavailable("consentimento explícito ausente")
    if account not in {"gmail", "google-calendar"}:
        raise ConnectorUnavailable("conta de conector desconhecida")
    store.put(account, refresh_token)


def exchange_authorization_code(
    *,
    code: str,
    verifier: str,
    transport: Callable[[dict[str, str]], dict[str, str]],
    consent: bool,
) -> dict[str, str]:
    """Troca o código só pelo transporte injetado. Não escolhe um cliente HTTP."""
    if not consent:
        raise ConnectorUnavailable("consentimento explícito ausente")
    if not oauth_client_id_configured():
        raise ConnectorUnavailable("client ID ausente")
    if not code or not verifier:
        raise ConnectorUnavailable("código PKCE ausente")
    import os
    payload = {
        "client_id": os.environ["JARVIS_GOOGLE_OAUTH_CLIENT_ID"].strip(),
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    result = transport(payload)
    if "refresh_token" not in result or "access_token" not in result:
        raise ConnectorUnavailable("resposta de token incompleta")
    return {"refresh_token": result["refresh_token"], "access_token": result["access_token"]}
