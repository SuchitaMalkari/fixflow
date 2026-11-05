"""The agent's tools: warranty lookup, ticket creation and human escalation, backed by SQLite.

The same functions are used by the agent, the REST API and the MCP server, so behaviour is identical everywhere.
"""

from __future__ import annotations

import csv
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .schemas import Ticket, Warranty

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    serial TEXT PRIMARY KEY, model TEXT, owner_email TEXT,
    purchase_date TEXT, warranty_end TEXT, plan TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, created_at TEXT, status TEXT, team TEXT, category TEXT,
    urgency TEXT, summary TEXT, request_text TEXT, serial TEXT
);
"""


class Store:
    """Small SQLite wrapper. Pass ':memory:' for tests and evaluations so nothing is written to disk."""

    def __init__(self, db_path: str | Path, devices_csv: Path | None = None) -> None:
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        if devices_csv is not None:
            self.load_devices(devices_csv)

    def load_devices(self, csv_path: Path) -> int:
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with self._lock, self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO devices VALUES (:serial, :model, :owner_email, :purchase_date, :warranty_end, :plan)",
                rows,
            )
        return len(rows)

    # ---- tools -------------------------------------------------------------------------------------

    def check_warranty(self, serial: str, today: date | None = None) -> Warranty | None:
        row = self.conn.execute(
            "SELECT * FROM devices WHERE serial = ?", (serial.strip().upper(),)
        ).fetchone()
        if row is None:
            return None
        today = today or date.today()
        in_warranty = date.fromisoformat(row["warranty_end"]) >= today
        return Warranty(
            serial=row["serial"],
            model=row["model"],
            plan=row["plan"],
            warranty_end=row["warranty_end"],
            in_warranty=in_warranty,
            covers_accidental_damage=in_warranty and row["plan"] == "premium",
        )

    def create_ticket(
        self,
        *,
        team: str,
        category: str,
        urgency: str,
        summary: str,
        request_text: str,
        serial: str | None = None,
        status: str = "open",
    ) -> Ticket:
        ticket = Ticket(
            id="FF-" + uuid.uuid4().hex[:8].upper(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            status=status,
            team=team,
            category=category,
            urgency=urgency,
            summary=summary[:300],
            request_text=request_text,
            serial=serial,
        )
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO tickets VALUES (:id, :created_at, :status, :team, :category, :urgency, :summary, :request_text, :serial)",
                ticket.model_dump(),
            )
        return ticket

    def escalate_to_human(self, *, reason: str, urgency: str, request_text: str, serial: str | None, category: str) -> Ticket:
        return self.create_ticket(
            team="safety_response" if category == "safety_hazard" else "human_review",
            category=category,
            urgency=urgency,
            summary=f"ESCALATED: {reason}",
            request_text=request_text,
            serial=serial,
            status="needs_human",
        )

    def list_tickets(self, limit: int = 50) -> list[Ticket]:
        rows = self.conn.execute(
            "SELECT * FROM tickets ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Ticket(**dict(r)) for r in rows]

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        row = self.conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return Ticket(**dict(row)) if row else None
