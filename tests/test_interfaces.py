"""The MCP server, the REST API and the evaluation harness."""

import asyncio
import json

import pytest

from fixflow import evals


def test_mcp_server_exposes_tools(monkeypatch, agent):
    from fixflow import mcp_server

    monkeypatch.setattr(mcp_server, "get_agent", lambda: agent)

    async def run():
        names = {t.name for t in await mcp_server.server.list_tools()}
        assert names == {"triage_request", "search_manuals", "check_warranty", "create_ticket", "get_ticket"}
        result = await mcp_server.server.call_tool("check_warranty", {"serial": "NV5T1R43"})
        assert json.loads(result.content[0].text)["model"] == "Vector 15 Pro"
        bad = await mcp_server.server.call_tool("create_ticket", {"category": "x", "urgency": "low", "summary": "s"})
        assert "error" in json.loads(bad.content[0].text)

    asyncio.run(run())


def test_api(monkeypatch, agent):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from fixflow import api

    monkeypatch.setattr(api, "get_agent", lambda: agent)
    client = TestClient(api.app)
    assert client.get("/health").json()["status"] == "ok"
    r = client.post("/triage", json={"text": "I dropped my laptop and the screen cracked"})
    assert r.status_code == 200 and r.json()["action"] == "ticket"
    ticket_id = r.json()["ticket_id"]
    assert client.get(f"/tickets/{ticket_id}").status_code == 200
    assert client.get("/tickets/FF-NOPE").status_code == 404
    assert client.post("/triage", json={"text": ""}).status_code == 422


def test_eval_meets_quality_bar():
    report = evals.evaluate("test", "v2")
    assert report.n == 30
    assert report.safety_escalated == report.safety_total  # safety recall must be perfect
    assert report.pct("action") >= 90
