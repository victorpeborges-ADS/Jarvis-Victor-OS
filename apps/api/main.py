from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
import hashlib
import hmac
import os
import re
import sqlite3
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from pydantic import ValidationError

from calendar_sim_api import router as calendar_sim_router
from calendar_simulator import CalendarProvider, CalendarSyncService
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
from local_automations import LocalAutomationScheduler, run_app_worker
from mission_api import router as mission_router
from review_api import router as review_router
from knowledge_api import router as knowledge_router
from selected_source_api import router as selected_source_router
from native_app_api import router as native_app_router
from native_runtime import NativeProtocolBoundary, NativeRuntimeIdentity, create_native_runtime_router
from loopback import ALLOWED_ORIGINS, is_allowed_host_header, is_loopback_address
from memory_store import MemoryStoreError, SQLiteMemoryStore
from database_leases import LeaseError
from restore_activation import ActivationError
from mission_engine import recover_interrupted
from workflow_executor import WorkflowExecutor
from conversation_gateway import Budget, ConversationGateway, FakeProvider, ProviderOutput
from skill_registry import Permission, SkillRegistry
from server_config import LocalServerConfig, validate_local_server_config

demo_router = APIRouter()


def fixture_or_422() -> dict:
    try:
        return read_raw_fixture()
    except FixtureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@demo_router.get("/health", response_model=HealthOut)
def health(request: Request, response: Response) -> HealthOut:
    # The E2E runner proves that its child process owns this listener with a
    # per-run HMAC challenge. The proof is absent in normal application runs.
    token = os.environ.get("JARVIS_E2E_READY_TOKEN")
    nonce = request.headers.get("x-jarvis-e2e-nonce", "")
    if token and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) and re.fullmatch(r"[0-9a-f]{64}", nonce):
        proof = hmac.new(token.encode("ascii"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
        response.headers["X-JARVIS-E2E-Ready-Proof"] = proof
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
    calendar_provider = CalendarProvider()
    calendar_sync_service = CalendarSyncService(store, calendar_provider)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Revalidate values at startup in case the frozen dataclass was altered
        # through low-level Python APIs after app construction.
        validate_local_server_config(config)
        # The loopback launcher has no authenticated Keychain bootstrap channel.
        # Keep the store locked instead of opening/creating the configured path.
        with store.runtime():
            yield

    app = FastAPI(
        title="JARVIS API — Gate 1 mock",
        description=(
            "Endpoints mock com dados DEMO fictícios. Nenhuma integração real. "
            "O Calendar do Gate 2.0-D é inteiramente simulado. "
            "domain_id é classificação de memória, não autorização de acesso. "
            "Rotas /real exigem sessão local e concessão."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.memory_store = store
    app.state.calendar_sim_provider = calendar_provider
    app.state.calendar_sync_service = calendar_sync_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(ALLOWED_ORIGINS),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-csrf-token"],
    )
    app.include_router(demo_router)
    app.include_router(real_router)
    app.include_router(calendar_sim_router)
    app.include_router(mission_router)
    app.include_router(review_router)
    app.include_router(knowledge_router)
    app.include_router(selected_source_router)

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

    for error_type in (MemoryStoreError, LeaseError, ActivationError, sqlite3.Error, OSError):
        app.add_exception_handler(error_type, memory_store_unavailable)

    return app


def create_native_app(
    identity: NativeRuntimeIdentity,
    *,
    database_path: str | Path | None = None,
) -> FastAPI:
    """Build the closed UDS-only app; web/demo routers are deliberately absent."""
    store = SQLiteMemoryStore(database_path)
    automation_scheduler = LocalAutomationScheduler(store)
    calendar_provider = CalendarProvider()
    calendar_sync_service = CalendarSyncService(store, calendar_provider)
    prepared_answer = {"text": ""}
    conversation_provider = FakeProvider(
        lambda _call, _cancel, _deadline, _clock: ProviderOutput(
            text=prepared_answer["text"], output_tokens=1, cost="unmeasured", repeat=False
        )
    )
    conversation_gateway = ConversationGateway(conversation_provider)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        with store.runtime():
            original_umask = os.umask(0o077)
            artifact_storage = None
            try:
                artifact_storage = tempfile.TemporaryDirectory(prefix="jarvis-synthetic-artifacts-")
                artifact_root = Path(artifact_storage.name)
                approved_root = artifact_root / "approved"
                state_dir = artifact_root / "state"
                approved_root.mkdir(mode=0o700)
                state_dir.mkdir(mode=0o700)
                skill_registry = SkillRegistry(approved_root, state_dir)
            except BaseException:
                if artifact_storage is not None:
                    artifact_storage.cleanup()
                raise
            finally:
                os.umask(original_umask)
            with artifact_storage:
                _app.state.skill_registry = skill_registry
                _app.state.storage_worker = None
                _app.state.storage_lifecycle_lock = asyncio.Lock()
                try:
                    yield
                finally:
                    worker = _app.state.storage_worker
                    if worker is not None:
                        worker.cancel()
                        try:
                            await worker
                        except asyncio.CancelledError:
                            pass
                    conversation_gateway.clear_all()
                    store.lock()
                    _app.state.skill_registry = None

    app = FastAPI(
        title="JARVIS MAC-003 local runtime",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.memory_store = store
    app.state.local_automation_scheduler = automation_scheduler
    app.state.calendar_sim_provider = calendar_provider
    app.state.calendar_sync_service = calendar_sync_service
    app.state.conversation_gateway = conversation_gateway
    app.state.grounded_reply = prepared_answer
    app.state.grounded_read_lock = threading.Lock()
    app.state.conversation_cancellations = {}
    app.state.conversation_cancellation_lock = threading.Lock()
    app.state.grounded_documents = ()
    app.state.skill_registry = None
    app.include_router(create_native_runtime_router(identity))
    app.include_router(native_app_router)

    @app.middleware("http")
    async def require_unlocked_storage(request: Request, call_next):
        bootstrap_routes = {
            "/v1/app/storage/status",
            "/v1/app/storage/unlock",
            "/v1/app/storage/lock",
        }
        if (
            request.url.path.startswith("/v1/app/")
            and request.url.path not in bootstrap_routes
            and not store.is_unlocked
        ):
            return PlainTextResponse("ok=false\ncode=storage_locked\n", status_code=200)
        return await call_next(request)

    @app.exception_handler(MemoryStoreError)
    @app.exception_handler(LeaseError)
    @app.exception_handler(ActivationError)
    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def memory_store_unavailable(_request: Request, _exc: Exception):
        return PlainTextResponse("ok=false\ncode=operation_failed\n", status_code=200)

    # Keep the closed protocol boundary outermost: lock-state middleware must
    # only run after the authenticated envelope has been admitted and decoded.
    app.add_middleware(NativeProtocolBoundary, identity=identity)
    return app
