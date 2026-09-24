"""Sobe a API apenas em loopback. Não abre porta pública."""

import os

import uvicorn

from main import create_app
from server_config import LocalServerConfig


def main() -> None:
    config = LocalServerConfig(
        host=os.environ.get("JARVIS_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("JARVIS_BIND_PORT", "8000")),
    )
    config.validate()
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        proxy_headers=False,
        forwarded_allow_ips="",
        access_log=False,
    )


if __name__ == "__main__":
    main()
