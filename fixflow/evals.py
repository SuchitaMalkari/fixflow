"""Evaluation: run labeled tickets through the agent and measure how often it is right.

Usage:
    python -m fixflow.evals                       # test split, offline, retriever v2
    python -m fixflow.evals --split dev --retriever v1
    python -m fixflow.evals --compare             # v1 vs v2 on dev and test, writes results/
    FIXFLOW_PROVIDER=anthropic python -m fixflow.evals --compare

The dev split (20 tickets) is the only data used while tuning. The test split (30 tickets) is held out.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent import FixFlowAgent
from .config import ROOT, Settings
from .schemas import SupportRequest
from .tools import Store


def load_tickets(path: Path, split: str | None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if split in (None, "all", r["split"])]


@dataclass
class Report:
    name: str
    n: int = 0
    correct: dict[str, int] = field(default_factory=lambda: {
        "category": 0, "team": 0, "action": 0, "urgency": 0, "hit@1": 0, "hit@3": 0})
    escalate_tp: int = 0
    escalate_fp: int = 0
    escalate_fn: int = 0
    safety_total: int = 0
    safety_escalated: int = 0
    failures: list[dict] = field(default_factory=list)
    seconds: float = 0.0

    def pct(self, key: str) -> float:
        return round(100 * self.correct[key] / self.n, 1) if self.n else 0.0

    def summary(self) -> dict:
        p = self.escalate_tp / (self.escalate_tp + self.escalate_fp) if (self.escalate_tp + self.escalate_fp) else 1.0
        r = self.escalate_tp / (self.escalate_tp + self.escalate_fn) if (self.escalate_tp + self.escalate_fn) else 1.0
        return {
            "name": self.name, "tickets": self.n,
            **{f"{k}_accuracy_pct": self.pct(k) for k in ("category", "team", "action", "urgency")},
            "retrieval_hit@1_pct": self.pct("hit@1"), "retrieval_hit@3_pct": self.pct("hit@3"),
            "escalation_precision_pct": round(100 * p, 1), "escalation_recall_pct": round(100 * r, 1),
            "safety_cases_escalated": f"{self.safety_escalated}/{self.safety_total}",
            "avg_ms_per_ticket": round(1000 * self.seconds / self.n, 1) if self.n else 0.0,
        }


def evaluate(split: str = "test", retriever: str = "v2", settings: Settings | None = None) -> Report:
    settings = settings or Settings()
    store = Store(":memory:", settings.devices_csv)  # never write eval tickets to the real database
    agent = FixFlowAgent(settings, store=store, retriever_version=retriever)
    report = Report(name=f"{split}/{retriever}/{agent.triager.name}")
    start = time.perf_counter()
    for row in load_tickets(settings.eval_file, split):
        exp = row["expected"]
        res = agent.handle(SupportRequest(text=row["text"], serial=row.get("serial")))
        retrieved = [h.chunk.article_id for h in agent.retriever.search_articles(row["text"], k=3)]
        got = {"category": res.category, "team": res.team, "action": res.action, "urgency": res.urgency}
        report.n += 1
        for key in got:
            report.correct[key] += got[key] == exp[key]
        report.correct["hit@1"] += retrieved[:1] == [exp["article"]]
        report.correct["hit@3"] += exp["article"] in retrieved
        if exp["action"] == "escalate" and res.action == "escalate":
            report.escalate_tp += 1
        elif res.action == "escalate":
            report.escalate_fp += 1
        elif exp["action"] == "escalate":
            report.escalate_fn += 1
        if exp["category"] == "safety_hazard":
            report.safety_total += 1
            report.safety_escalated += res.action == "escalate"
        wrong = [k for k in ("category", "action") if got[k] != exp[k]]
        if wrong:
            report.failures.append({"id": row["id"], "text": row["text"], "wrong": wrong,
                                    "expected": {k: exp[k] for k in wrong}, "got": {k: got[k] for k in wrong},
                                    "confidence": res.confidence})
    report.seconds = time.perf_counter() - start
    return report


def to_markdown(reports: list[Report]) -> str:
    rows = [r.summary() for r in reports]
    keys = [k for k in rows[0] if k != "name"]
    lines = ["| Metric | " + " | ".join(r["name"] for r in rows) + " |",
             "| --- | " + " | ".join("---" for _ in rows) + " |"]
    lines += [f"| {k} | " + " | ".join(str(r[k]) for r in rows) + " |" for k in keys]
    out = ["# FixFlow evaluation results", "", *lines, ""]
    for r in reports:
        if r.failures:
            out += [f"## Misses: {r.name}", ""]
            out += [f"- `{f['id']}` \"{f['text']}\": expected {f['expected']}, got {f['got']} "
                    f"(confidence {f['confidence']:.2f})" for f in r.failures]
            out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate FixFlow on labeled tickets.")
    parser.add_argument("--split", default="test", choices=["dev", "test", "all"])
    parser.add_argument("--retriever", default="v2", choices=["v1", "v2"])
    parser.add_argument("--compare", action="store_true", help="v1 vs v2 on dev and test; writes results/")
    parser.add_argument("--min-action-accuracy", type=float, default=None,
                        help="exit with an error if test action accuracy falls below this (used in CI)")
    args = parser.parse_args()

    if args.compare:
        reports = [evaluate(s, v) for s in ("dev", "test") for v in ("v1", "v2")]
    else:
        reports = [evaluate(args.split, args.retriever)]
    md = to_markdown(reports)
    print(md)
    if args.compare:
        out = ROOT / "results"
        out.mkdir(exist_ok=True)
        provider = Settings().provider
        (out / f"eval_{provider}.md").write_text(md + "\n", encoding="utf-8")
        (out / f"eval_{provider}.json").write_text(
            json.dumps([r.summary() for r in reports], indent=2) + "\n", encoding="utf-8")
    if args.min_action_accuracy is not None:
        score = reports[-1].pct("action")
        if score < args.min_action_accuracy:
            raise SystemExit(f"action accuracy {score}% is below the {args.min_action_accuracy}% gate")


if __name__ == "__main__":
    main()
