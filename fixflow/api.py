"""REST API. Run with:  uvicorn fixflow.api:app --reload   then open http://localhost:8000/docs"""

from __future__ import annotations

import os
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


# A few sample requests so the issue board is not empty on a fresh server. Set FIXFLOW_SEED_DEMO=0 to turn off.
DEMO_REQUESTS = [
    ("My laptop is plugged in but the battery stays at 80%", "PF3K9X21"),
    ("wifi disconnects every 10 min, other devices at home are fine", "VX8E2J64"),
    ("The bottom of my laptop is bulging and the touchpad is lifting up", "PF7Q2M88"),
    ("Dropped my laptop and the screen is cracked in the corner", "AB4L8P32"),
    ("Can you install Adobe Illustrator on my machine?", "VX8E2J64"),
    ("Nobody on the 3rd floor can connect to the VPN since this morning", None),
    ("screen keeps flickering when i scroll in chrome", "NM9X4C77"),
    ("I forgot my password and now my account is locked", None),
]


@lru_cache(maxsize=1)
def get_agent() -> FixFlowAgent:
    agent = FixFlowAgent()
    if os.environ.get("FIXFLOW_SEED_DEMO", "1") != "0" and agent.store.request_stats()["total"] == 0:
        for text, serial in DEMO_REQUESTS:
            agent.handle(SupportRequest(text=text, serial=serial))
    return agent


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


@app.get("/activity")
def activity(limit: int = Query(20, ge=1, le=100)) -> dict:
    """Recent requests and totals, for the live issue board."""
    store = get_agent().store
    return {"stats": store.request_stats(), "recent": store.recent_requests(limit)}


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(limit: int = Query(50, ge=1, le=500)) -> list[Ticket]:
    return get_agent().store.list_tickets(limit)


@app.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: str) -> Ticket:
    ticket = get_agent().store.get_ticket(ticket_id.upper())
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket
