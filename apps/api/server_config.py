"""Single source of truth for supported local API binding."""

from dataclasses import dataclass

from loopback import assert_bind_host


@dataclass(frozen=True)
class LocalServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        assert_bind_host(self.host)
        if isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("porta local inválida")
