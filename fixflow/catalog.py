"""Approved-software catalog: tells the agent whether an app can be self-installed or needs a request."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CatalogApp:
    name: str
    aliases: tuple[str, ...]
    install_via: str


class SoftwareCatalog:
    def __init__(self, csv_path: Path) -> None:
        with open(csv_path, newline="", encoding="utf-8") as f:
            self.apps = [
                CatalogApp(r["name"], tuple(a.strip().lower() for a in r["aliases"].split("|")), r["install_via"])
                for r in csv.DictReader(f)
            ]

    def find_in_text(self, text: str) -> list[CatalogApp]:
        """Approved apps mentioned in free text, matched on whole words."""
        lowered = text.lower()
        return [
            app
            for app in self.apps
            if any(re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered) for alias in app.aliases)
        ]
