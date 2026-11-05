"""MCP server: exposes FixFlow's tools so any MCP client (for example Claude Desktop) can use them.

Run it with:  python -m fixflow.mcp_server
Then add it to the client's MCP config (see the README). The client's model can now search the manuals,
check warranties and open tickets through FixFlow, using the same code paths as the REST API.
"""

from __future__ import annotations

from functools import lru_cache

from mcp.server.mcpserver import MCPServer

from .agent import FixFlowAgent
from .schemas import CATEGORY_TO_TEAM, SupportRequest

server = MCPServer(
    name="fixflow",
    instructions=(
        "FixFlow is an IT-support toolkit for laptops. Use triage_request for a full automated decision, "
        "or the individual tools to search the manuals, check a device warranty or open a ticket. "
        "Never close safety issues yourself: swelling, smoke or burning smells must use escalate."
    ),
)


@lru_cache(maxsize=1)
def get_agent() -> FixFlowAgent:
    return FixFlowAgent()


@server.tool()
def triage_request(text: str, serial: str | None = None) -> dict:
    """Run the full FixFlow workflow on a support request: classify it, find the fix, check warranty,
    then answer it, open a ticket, or escalate it to a person. Returns the decision and the reasons."""
    return get_agent().handle(SupportRequest(text=text, serial=serial)).model_dump()


@server.tool()
def search_manuals(query: str, k: int = 3) -> list[dict]:
    """Search the laptop troubleshooting knowledge base. Returns the best-matching sections with article IDs."""
    hits = get_agent().retriever.search_articles(query, k=max(1, min(k, 10)))
    return [
        {"article_id": h.chunk.article_id, "title": h.chunk.title, "section": h.chunk.section,
         "text": h.chunk.text, "score": h.score}
        for h in hits
    ]


@server.tool()
def check_warranty(serial: str) -> dict:
    """Look up a device by serial number: model, plan and whether it is still under warranty."""
    warranty = get_agent().store.check_warranty(serial)
    return warranty.model_dump() if warranty else {"error": f"No device found with serial {serial}"}


@server.tool()
def create_ticket(category: str, urgency: str, summary: str, serial: str | None = None) -> dict:
    """Open a support ticket. category must be one of the FixFlow categories; it decides the team."""
    if category not in CATEGORY_TO_TEAM:
        return {"error": f"Unknown category. Use one of: {', '.join(CATEGORY_TO_TEAM)}"}
    if urgency not in ("low", "medium", "high", "critical"):
        return {"error": "urgency must be low, medium, high or critical"}
    ticket = get_agent().store.create_ticket(
        team=CATEGORY_TO_TEAM[category], category=category, urgency=urgency,
        summary=summary, request_text=summary, serial=serial,
    )
    return ticket.model_dump()


@server.tool()
def get_ticket(ticket_id: str) -> dict:
    """Get the status and details of a ticket by its ID (for example FF-1A2B3C4D)."""
    ticket = get_agent().store.get_ticket(ticket_id.strip().upper())
    return ticket.model_dump() if ticket else {"error": f"No ticket {ticket_id}"}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
