"""Sobe a API web em loopback ou o runtime MAC-003 somente em UDS."""

import asyncio
import os
import sys
import threading

import uvicorn

from main import create_app, create_native_app
from native_runtime import INIT_MAX_BYTES, NativeRuntimeIdentity, read_child_init
from server_config import LocalServerConfig


def main() -> None:
    args = sys.argv[1:]
    if args:
        if len(args) != 2 or args[0] != "--desktop-runtime" or not args[1]:
            raise SystemExit(64)
        raise SystemExit(run_desktop_runtime(args[1]))
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


class _ControlState:
    def __init__(self, identity: NativeRuntimeIdentity):
        self.identity = identity
        self.server: _ReadyServer | None = None
        self.exit_code: int | None = None
        self.lock = threading.Lock()

    def request_exit(self, exit_code: int) -> None:
        with self.lock:
            if self.exit_code is None or exit_code == 0:
                self.exit_code = exit_code
            if self.server is not None:
                self.server.should_exit = True


class _ReadyServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, identity: NativeRuntimeIdentity):
        super().__init__(config)
        self.identity = identity

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            sys.stdout.write(f"JARVIS_RUNTIME_READY {self.identity.instance_id}\n")
            sys.stdout.flush()


def _read_control(identity: NativeRuntimeIdentity, state: _ControlState) -> None:
    stop_line = f"JARVIS_RUNTIME_STOP {identity.instance_id}\n".encode("ascii")
    ack_line = f"JARVIS_RUNTIME_ACK {identity.instance_id}\n".encode("ascii")
    try:
        while True:
            line = sys.stdin.buffer.readline(INIT_MAX_BYTES + 1)
            if not line:
                state.request_exit(48)
                identity.acknowledged.set()
                return
            if len(line) > INIT_MAX_BYTES or not line.endswith(b"\n"):
                state.request_exit(48)
                return
            if line == ack_line:
                identity.acknowledged.set()
            elif line == stop_line:
                state.request_exit(0)
                identity.acknowledged.set()
                return
    except OSError:
        state.request_exit(48)
        identity.acknowledged.set()


def run_desktop_runtime(expected_instance_id: str) -> int:
    """Run one direct Python child; its stdin/stdout remain supervisor-owned."""
    record = bytearray(sys.stdin.buffer.readline(INIT_MAX_BYTES + 1))
    try:
        identity = read_child_init(record, expected_instance_id)
    except (ValueError, UnicodeError, OSError):
        record[:] = b"\x00" * len(record)
        return 64

    state = _ControlState(identity)
    app = create_native_app(identity)
    config = uvicorn.Config(
        app,
        uds="runtime.sock",
        access_log=False,
        log_level="critical",
        server_header=False,
        date_header=False,
        h11_max_incomplete_event_size=1024,
    )
    server = _ReadyServer(config, identity)
    state.server = server
    control = threading.Thread(target=_read_control, args=(identity, state), name="jarvis-supervisor-pipe", daemon=True)
    control.start()

    previous_mask = os.umask(0o177)
    exit_code = 46
    try:
        asyncio.run(server.serve())
        with state.lock:
            exit_code = state.exit_code if state.exit_code is not None else 46
    except BaseException:
        exit_code = 46
    finally:
        os.umask(previous_mask)
        identity.clear()
        # The parent removes runtime.sock with unlinkat relative to the
        # directory handle captured before spawning this process.
    return exit_code


if __name__ == "__main__":
    main()
