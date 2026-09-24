from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI(
    title="JARVIS API — Gate 1 mock",
    description=(
        "Endpoints mock com dados DEMO fictícios. Nenhuma integração real. "
        "domain_id é classificação de memória, não autorização de acesso."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def fixture_or_422() -> dict:
    try:
        return read_raw_fixture()
    except FixtureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", gate=1, mode="mock", demo=True)


@app.get("/briefing")
def briefing() -> dict:
    return fixture_or_422().get("briefing", {})


@app.get("/events", response_model=list[EventOut])
def events() -> list[EventOut]:
    return parse_collection(fixture_or_422().get("events"), EventOut, "Event")


@app.get("/sources", response_model=list[SourceOut])
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


@app.get("/inbox", response_model=list[CaptureOut])
def inbox() -> list[CaptureOut]:
    return parse_collection(fixture_or_422().get("inbox"), CaptureOut, "FixtureCapture")


@app.get("/domains", response_model=list[DomainOut])
def domains() -> list[DomainOut]:
    return parse_collection(fixture_or_422().get("domains"), DomainOut, "Domain")


@app.get("/proposals")
def proposals() -> list:
    data = fixture_or_422().get("proposals", [])
    return data if isinstance(data, list) else []


@app.get("/approvals")
def approvals() -> list:
    data = fixture_or_422().get("approvals", [])
    return data if isinstance(data, list) else []
