from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
from pathlib import Path

app = FastAPI(
    title="JARVIS API — Gate 1 mock",
    description="Endpoints mock com dados DEMO fictícios. Nenhuma integração real.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "demo.json"

def load_fixtures():
    if not FIXTURES.exists():
        return {"meta": {"demo": True}, "events": [], "sources": [], "briefing": {}}
    return json.loads(FIXTURES.read_text())

@app.get("/health")
def health():
    return {"status": "ok", "gate": 1, "mode": "mock", "demo": True}

@app.get("/briefing")
def briefing():
    data = load_fixtures()
    return data.get("briefing", {})

@app.get("/events")
def events():
    data = load_fixtures()
    return data.get("events", [])

@app.get("/sources")
def sources():
    data = load_fixtures()
    return data.get("sources", [])

@app.get("/proposals")
def proposals():
    data = load_fixtures()
    return data.get("proposals", [])

@app.get("/inbox")
def inbox():
    data = load_fixtures()
    return data.get("inbox", [])

@app.get("/approvals")
def approvals():
    data = load_fixtures()
    return data.get("approvals", [])

@app.get("/domains")
def domains():
    data = load_fixtures()
    return data.get("domains", [])
