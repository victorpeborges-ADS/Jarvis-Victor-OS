"""Política de host, origem e endereço local do servidor."""

from __future__ import annotations

import ipaddress
import sys
from urllib.parse import urlsplit

LOOPBACK_BIND_HOSTS = frozenset({"127.0.0.1", "::1"})
ALLOWED_HOST_NAMES = frozenset({"localhost"})
ALLOWED_ORIGINS = frozenset(
    {
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://[::1]:3000",
    }
)
_SAFE_RUNNER_ACTIVE = False


def is_loopback_address(value: str | None) -> bool:
    if not value:
        return False
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def parse_host_header(value: str | None) -> str | None:
    if not value or any(char in value for char in "\r\n/@"):
        return None
    try:
        parsed = urlsplit(f"//{value}")
        hostname = parsed.hostname
        # Force invalid/out-of-range ports to fail rather than being ignored.
        _ = parsed.port
    except ValueError:
        return None
    return hostname.lower() if hostname else None


def is_allowed_host_header(value: str | None) -> bool:
    hostname = parse_host_header(value)
    return hostname == "localhost" or is_loopback_address(hostname)


def require_allowed_origin(origin: str | None) -> None:
    if origin is None or origin not in ALLOWED_ORIGINS:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="origem ausente ou recusada")


def assert_bind_host(host: str) -> str:
    if host not in LOOPBACK_BIND_HOSTS:
        raise RuntimeError("bind não local recusado")
    return host


def activate_supported_runner() -> None:
    global _SAFE_RUNNER_ACTIVE
    _SAFE_RUNNER_ACTIVE = True


def reject_direct_uvicorn_cli(argv0: str | None = None) -> None:
    """Only the guarded serve.py may use the Uvicorn CLI/import target."""
    executable = (argv0 or sys.argv[0]).lower()
    is_uvicorn_cli = "uvicorn" in executable
    if is_uvicorn_cli and not _SAFE_RUNNER_ACTIVE:
        raise RuntimeError("inicialização direta por Uvicorn recusada; use python serve.py")
