from datetime import date

from fixflow.catalog import SoftwareCatalog


def test_warranty_in_and_out(store):
    active = store.check_warranty("PF3K9X21", today=date(2026, 11, 1))
    assert active.in_warranty and active.covers_accidental_damage
    expired = store.check_warranty("pf7q2m88", today=date(2026, 11, 1))  # lookup is case-insensitive
    assert not expired.in_warranty and not expired.covers_accidental_damage


def test_unknown_serial(store):
    assert store.check_warranty("NOPE0000") is None


def test_ticket_roundtrip(store):
    t = store.create_ticket(team="network_ops", category="connectivity", urgency="high",
                            summary="VPN down", request_text="VPN down for the floor")
    assert t.id.startswith("FF-")
    assert store.get_ticket(t.id).summary == "VPN down"
    assert store.list_tickets()[0].id == t.id


def test_escalation_routes_safety(store):
    t = store.escalate_to_human(reason="smoke", urgency="critical", request_text="smoke",
                                serial=None, category="safety_hazard")
    assert t.status == "needs_human" and t.team == "safety_response"


def test_catalog(settings):
    catalog = SoftwareCatalog(settings.data_dir / "software_catalog.csv")
    assert [a.name for a in catalog.find_in_text("need VS Code and python")] == ["Visual Studio Code", "Python"]
    assert catalog.find_in_text("install Tableau") == []
    assert catalog.find_in_text("legitimate") == []  # 'git' must match whole words only
