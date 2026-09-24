"""Sobe a API apenas em loopback. Não abre porta pública."""

import os

import uvicorn

from loopback import activate_supported_runner, assert_bind_host


def main() -> None:
    host = assert_bind_host(os.environ.get("JARVIS_BIND_HOST", "127.0.0.1"))
    port = int(os.environ.get("JARVIS_BIND_PORT", "8000"))
    activate_supported_runner()
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        proxy_headers=False,
        forwarded_allow_ips="",
        access_log=False,
    )


if __name__ == "__main__":
    main()
