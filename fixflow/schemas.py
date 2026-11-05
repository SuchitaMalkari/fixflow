"""Typed data models shared by the agent, the API and the MCP server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "battery_power",
    "display",
    "thermal",
    "input_devices",
    "physical_damage",
    "safety_hazard",
    "connectivity",
    "performance",
    "boot_os",
    "software",
    "account_access",
]
Team = Literal["hardware_repair", "network_ops", "software_support", "it_helpdesk", "safety_response"]
Urgency = Literal["low", "medium", "high", "critical"]
Action = Literal["self_serve", "ticket", "escalate"]

CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]

CATEGORY_TO_TEAM: dict[str, str] = {
    "battery_power": "hardware_repair",
    "display": "hardware_repair",
    "thermal": "hardware_repair",
    "input_devices": "hardware_repair",
    "physical_damage": "hardware_repair",
    "safety_hazard": "safety_response",
    "connectivity": "network_ops",
    "performance": "software_support",
    "boot_os": "software_support",
    "software": "software_support",
    "account_access": "it_helpdesk",
}


class SupportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="The user's problem in their own words.")
    serial: str | None = Field(default=None, description="Device serial number, if known.")
    email: str | None = Field(default=None, description="Requester email, if known.")


class Chunk(BaseModel):
    article_id: str
    title: str
    category: str
    section: str
    text: str


class SearchHit(BaseModel):
    chunk: Chunk
    score: float


class Triage(BaseModel):
    """What the classifier (LLM or offline) decided about a request."""

    category: Category
    urgency: Urgency
    confidence: float = Field(ge=0.0, le=1.0)
    safety_flag: bool = False
    wants_human: bool = False
    data_loss_risk: bool = False
    security_incident: bool = False
    already_tried: bool = False
    multi_user: bool = False
    needs_specialist: bool = False
    summary: str = ""


class Warranty(BaseModel):
    serial: str
    model: str
    plan: str
    warranty_end: str
    in_warranty: bool
    covers_accidental_damage: bool


class Ticket(BaseModel):
    id: str
    created_at: str
    status: str
    team: str
    category: str
    urgency: str
    summary: str
    request_text: str
    serial: str | None = None


class Resolution(BaseModel):
    """The agent's final answer for one request, including a step-by-step trace for debugging."""

    action: Action
    category: Category
    team: Team
    urgency: Urgency
    confidence: float
    answer: str
    citations: list[str] = []
    ticket_id: str | None = None
    warranty: Warranty | None = None
    reasons: list[str] = []
    trace: list[str] = []
