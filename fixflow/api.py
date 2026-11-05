"""REST API. Run with:  uvicorn fixflow.api:app --reload   then open http://localhost:8000/docs"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import __version__
from .agent import FixFlowAgent
from .schemas import Resolution, SupportRequest, Ticket

app = FastAPI(
    title="FixFlow",
    version=__version__,
    description="AI agent that triages IT-support requests: answer, open a ticket, or escalate to a person.",
)


@lru_cache(maxsize=1)
def get_agent() -> FixFlowAgent:
    return FixFlowAgent()


INDEX_HTML = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def home() -> str:
    """The demo page. The interactive API docs stay at /docs."""
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    agent = get_agent()
    return {"status": "ok", "version": __version__, "provider": agent.triager.name,
            "kb_chunks": len(agent.chunks)}


@app.post("/triage", response_model=Resolution)
def triage(request: SupportRequest) -> Resolution:
    return get_agent().handle(request)


@app.get("/search")
def search(q: str = Query(min_length=2), k: int = Query(3, ge=1, le=10)) -> list[dict]:
    return [
        {"article_id": h.chunk.article_id, "title": h.chunk.title, "section": h.chunk.section, "score": h.score}
        for h in get_agent().retriever.search_articles(q, k=k)
    ]


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(limit: int = Query(50, ge=1, le=500)) -> list[Ticket]:
    return get_agent().store.list_tickets(limit)


@app.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: str) -> Ticket:
    ticket = get_agent().store.get_ticket(ticket_id.upper())
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket
