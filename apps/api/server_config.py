"""Single source of truth for supported local API binding."""

from dataclasses import dataclass

from loopback import assert_bind_host


def validate_local_server_config(config: object) -> "LocalServerConfig":
    """Validate the concrete config and its current values without trusting callers."""
    if type(config) is not LocalServerConfig:
        raise TypeError("configuração deve ser uma instância exata de LocalServerConfig")

    host = getattr(config, "host", None)
    port = getattr(config, "port", None)
    if type(host) is not str:
        raise ValueError("host local inválido")
    assert_bind_host(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("porta local inválida")
    return config


@dataclass(frozen=True)
class LocalServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        validate_local_server_config(self)
