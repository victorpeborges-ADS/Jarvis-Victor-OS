from contextlib import asynccontextmanager
import sqlite3
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pydantic import ValidationError

from contract import (
    CaptureOut,
    DomainOut,
    EventOut,
    FixtureError,
    HealthOut,
    SourceOut,
    parse_collection,
    read_raw_fixture,
)
from local_security import router as real_router
from loopback import ALLOWED_ORIGINS, is_allowed_host_header, is_loopback_address
from memory_store import MemoryStoreError, SQLiteMemoryStore
from server_config import LocalServerConfig, validate_local_server_config

demo_router = APIRouter()


def fixture_or_422() -> dict:
    try:
        return read_raw_fixture()
    except FixtureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@demo_router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", gate=1, mode="mock", demo=True)


@demo_router.get("/briefing")
def briefing() -> dict:
    return fixture_or_422().get("briefing", {})


@demo_router.get("/events", response_model=list[EventOut])
def events() -> list[EventOut]:
    return parse_collection(fixture_or_422().get("events"), EventOut, "Event")


@demo_router.get("/sources", response_model=list[SourceOut])
def sources() -> list[SourceOut]:
    data = fixture_or_422().get("sources", [])
    if not isinstance(data, list):
        return []
    parsed = []
    for item in data:
        try:
            parsed.append(SourceOut.model_validate(item))
        except ValidationError:
            continue
    return parsed


@demo_router.get("/inbox", response_model=list[CaptureOut])
def inbox() -> list[CaptureOut]:
    return parse_collection(fixture_or_422().get("inbox"), CaptureOut, "FixtureCapture")


@demo_router.get("/domains", response_model=list[DomainOut])
def domains() -> list[DomainOut]:
    return parse_collection(fixture_or_422().get("domains"), DomainOut, "Domain")


@demo_router.get("/proposals")
def proposals() -> list:
    data = fixture_or_422().get("proposals", [])
    return data if isinstance(data, list) else []


@demo_router.get("/approvals")
def approvals() -> list:
    data = fixture_or_422().get("approvals", [])
    return data if isinstance(data, list) else []


def create_app(config: LocalServerConfig, *, database_path: str | Path | None = None) -> FastAPI:
    """Build the ASGI app only with an explicit loopback server configuration.

    There is intentionally no module-level ``app`` object: standard Uvicorn
    import strings such as ``main:app`` cannot bypass the local launcher.
    """
    validate_local_server_config(config)
    store = SQLiteMemoryStore(database_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Revalidate values at startup in case the frozen dataclass was altered
        # through low-level Python APIs after app construction.
        validate_local_server_config(config)
        store.initialize()
        yield

    app = FastAPI(
        title="JARVIS API — Gate 1 mock",
        description=(
            "Endpoints mock com dados DEMO fictícios. Nenhuma integração real. "
            "domain_id é classificação de memória, não autorização de acesso. "
            "Rotas /real exigem sessão local e concessão."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.memory_store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(ALLOWED_ORIGINS),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-csrf-token"],
    )
    app.include_router(demo_router)
    app.include_router(real_router)

    @app.middleware("http")
    async def local_transport_boundary(request: Request, call_next):
        # A process owner can write arbitrary Python that opens a public socket;
        # this ASGI boundary rejects traffic unless both actual endpoints are
        # loopback. The supported serve.py runner also binds only to loopback.
        server = request.scope.get("server")
        server_host = server[0] if server else None
        client_host = request.client.host if request.client else None
        if not is_allowed_host_header(request.headers.get("host")):
            response = JSONResponse({"detail": "host recusado"}, status_code=400)
        elif not is_loopback_address(server_host) or not is_loopback_address(client_host):
            response = JSONResponse({"detail": "acesso somente local"}, status_code=403)
        else:
            response = await call_next(request)
        dataset = "real" if request.url.path.startswith("/real") else "demo"
        response.headers["X-JARVIS-Dataset"] = dataset
        if request.url.path.startswith("/real"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_without_input(request: Request, exc: RequestValidationError):
        # Pydantic's default detail contains `input`; never echo a passphrase or body.
        detail = "credencial inválida" if request.url.path == "/real/session" else "requisição inválida"
        return JSONResponse({"detail": detail}, status_code=422)

    async def memory_store_unavailable(request: Request, exc: Exception):
        return JSONResponse({"detail": "memória local indisponível"}, status_code=503)

    for error_type in (MemoryStoreError, sqlite3.Error, OSError):
        app.add_exception_handler(error_type, memory_store_unavailable)

    return app
