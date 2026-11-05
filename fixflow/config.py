"""Settings, read from environment variables so the same code runs locally, in Docker and in CI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # "offline" needs no API key and is what CI uses. "anthropic" or "openai" call a real LLM.
    provider: str = field(default_factory=lambda: _env("FIXFLOW_PROVIDER", "offline").lower())
    model: str = field(default_factory=lambda: _env("FIXFLOW_MODEL", ""))
    data_dir: Path = field(default_factory=lambda: Path(_env("FIXFLOW_DATA_DIR", str(ROOT / "data"))))
    db_path: Path = field(default_factory=lambda: Path(_env("FIXFLOW_DB_PATH", str(ROOT / "fixflow.db"))))
    # Below this confidence the agent hands the request to a person instead of guessing.
    confidence_threshold: float = field(
        default_factory=lambda: float(_env("FIXFLOW_CONFIDENCE_THRESHOLD", "0.35"))
    )
    top_k: int = field(default_factory=lambda: int(_env("FIXFLOW_TOP_K", "3")))

    @property
    def kb_dir(self) -> Path:
        return self.data_dir / "kb"

    @property
    def devices_csv(self) -> Path:
        return self.data_dir / "devices.csv"

    @property
    def eval_file(self) -> Path:
        return self.data_dir / "eval" / "tickets.jsonl"

    def resolved_model(self) -> str:
        if self.model:
            return self.model
        return {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini"}.get(self.provider, "")
