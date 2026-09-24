"""Ligação local. Recusa qualquer interface que não seja loopback."""

LOOPBACK_BIND_HOSTS = frozenset({"127.0.0.1", "::1"})
ALLOWED_CLIENT_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
ALLOWED_ORIGINS = frozenset(
    {
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    }
)


def assert_bind_host(host: str) -> str:
    if host not in LOOPBACK_BIND_HOSTS:
        raise RuntimeError("exposição de rede recusada")
    return host
