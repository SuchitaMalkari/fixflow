import pytest

from fixflow.schemas import SupportRequest


def handle(agent, text, serial=None):
    return agent.handle(SupportRequest(text=text, serial=serial))


@pytest.mark.parametrize("text", [
    "There is smoke coming out of the vents",
    "the battery is swollen and the case is bulging",
    "burning smell from my laptop",
])
def test_safety_always_escalates(agent, text):
    r = handle(agent, text)
    assert r.action == "escalate" and r.team == "safety_response" and r.urgency == "critical"
    assert r.ticket_id


def test_security_incident_escalates(agent):
    r = handle(agent, "I see sign-ins on my account that weren't me")
    assert r.action == "escalate" and r.urgency == "critical"


def test_self_serve_cites_article(agent):
    r = handle(agent, "screen keeps flickering when I scroll")
    assert r.action == "self_serve" and r.citations == ["KB-004"] and r.ticket_id is None
    assert "Windows + Ctrl + Shift + B" in r.answer


def test_physical_damage_opens_ticket_with_warranty_note(agent):
    r = handle(agent, "I dropped my laptop and the screen cracked", serial="PF3K9X21")
    assert r.action == "ticket" and r.team == "hardware_repair" and r.warranty is not None
    assert agent.store.get_ticket(r.ticket_id) is not None


def test_already_tried_becomes_ticket(agent):
    r = handle(agent, "wifi still drops even after I updated drivers and reset the network")
    assert r.action == "ticket" and r.team == "network_ops"


def test_vague_request_is_not_guessed(agent):
    r = handle(agent, "pc not working")
    assert r.action == "escalate"
    assert any("Low confidence" in reason for reason in r.reasons)


def test_unapproved_software_needs_request(agent):
    assert handle(agent, "please install Tableau for me").action == "ticket"
    assert handle(agent, "need VS Code installed").action == "self_serve"


def test_trace_records_every_step(agent):
    r = handle(agent, "battery drains fast", serial="NV5T1R43")
    steps = [s.split(":")[0].split("[")[0] for s in r.trace]
    assert steps == ["retrieve", "triage", "check_warranty", "decide", "act"]


def test_every_request_is_logged(agent):
    handle(agent, "screen keeps flickering when I scroll")
    handle(agent, "there is smoke coming from the vents")
    rows = agent.store.recent_requests()
    assert [r["action"] for r in rows] == ["escalate", "self_serve"]
    assert rows[0]["reasons"] and rows[0]["trace"][0].startswith("retrieve")
