"""Descritores somente leitura de Gmail e Google Calendar.

Nenhum método abre rede, grava token ou devolve o client ID.
"""

from __future__ import annotations

import os

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
_GMAIL_SCOPE_LABEL = "gmail.readonly"
_CALENDAR_SCOPE_LABEL = "calendar.readonly"


class ConnectorUnavailable(RuntimeError):
    """O conector não tem consentimento e não pode chamar o provedor."""


def oauth_client_id_configured() -> bool:
    raw = os.environ.get("JARVIS_GOOGLE_OAUTH_CLIENT_ID")
    if raw is None:
        return False
    value = raw.strip()
    if not value or len(value) > 256:
        return False
    return all(33 <= ord(character) <= 126 for character in value)


def public_status() -> dict[str, str]:
    block = "consent_required" if oauth_client_id_configured() else "missing_oauth_client"
    return {
        "gmail": "not_connected",
        "gmail_block": block,
        "gmail_scope": _GMAIL_SCOPE_LABEL,
        "calendar": "not_connected",
        "calendar_block": block,
        "calendar_scope": _CALENDAR_SCOPE_LABEL,
        "calendar_sim": "synthetic_local",
    }


def read_gmail_messages() -> None:
    raise ConnectorUnavailable("gmail não conectado")


def read_google_calendar_events() -> None:
    raise ConnectorUnavailable("google calendar não conectado")
