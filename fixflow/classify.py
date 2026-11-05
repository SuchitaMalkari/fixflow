"""Offline triage: works with no API key, so the project runs anywhere and CI is free and repeatable.

Category comes from retrieval (which knowledge-base articles match best). Safety, security and escalation
signals come from explicit rules, because those decisions must be predictable and auditable, not guessed.
The LLM triager in llm.py produces the same Triage object, so the agent does not care which one ran.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .retrieval import Retriever
from .schemas import Triage

# Calibration constant: a top category score at or above this counts as a strong match.
STRONG_MATCH_SCORE = 6.0


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


SAFETY = [r"\bbulg", r"\bswell", r"\bswollen", r"\bsmok", r"\bburn(ing|t)? smell", r"\bspark", r"\bhiss",
          r"\bon fire\b", r"\bflames?\b", r"\btoo hot to (touch|hold)"]
SECURITY = [r"sign-?ins? .*(weren'?t|not) me", r"\bhack", r"\bcompromis", r"\bphish", r"don'?t recogni[sz]e .*sign",
            r"\bsomeone (else )?(logged|signed) in"]
WANTS_HUMAN = [r"\b(real|actual) (person|human)\b", r"\bspeak to (a|someone|the)\b", r"\btalk to (a|someone)\b",
               r"\bmanager\b", r"\bhuman\b", r"\bcall me\b"]
DATA_LOSS = [r"not backed up", r"\bno backup", r"isn'?t backed up", r"(lose|lost|losing) (all )?(my )?(data|files|work)",
             r"\bthesis\b"]
ALREADY_TRIED = [r"\balready\b", r"\bstill\b", r"\btried\b", r"\beven after\b", r"\bagain\b", r"\b(second|third|\d+(st|nd|rd|th)) time\b"]
MULTI_USER = [r"\bnobody\b", r"\beveryone\b", r"\bwhole (team|office|floor|department)\b", r"\ball of us\b",
              r"\b(floor|team|office) (can'?t|cannot|lost)\b", r"\bnobody on\b", r"\bentire\b"]
SPECIALIST = [r"\blines? on (my |the )?screen", r"\b(vertical|horizontal) .*lines\b", r"\bgrind", r"\bclick(ing)? noise",
              r"\bno lights?\b", r"\bshuts? (off|down) by itself", r"\bturns? off by itself", r"\bhealth (says|is|at) \d+",
              r"\b(new|lost) phone\b", r"authenticator", r"\bhear (windows|sounds)", r"\bnot in the (company )?portal\b",
              r"\bisn'?t in the (company )?portal\b"]
PHYSICAL = [r"\bspill", r"\bdropp?ed\b", r"\bcrack", r"\bsnapp?ed\b", r"\bfell off\b", r"\bbroken hinge", r"\bhinge\b",
            r"\bknocked\b.*\b(water|coffee|drink|glass)", r"\bliquid\b"]
INSTALL_REQUEST = [r"\binstall", r"\bneed .* installed", r"\bget (a )?(licen[cs]e|access to)\b", r"\bis there a way to get\b"]
HOW_TO = [r"^how (do|can|to)\b", r"\bhow do i\b", r"\bis it broken\?"]
CANT_WORK = [r"won'?t (turn on|boot|start)", r"\bno lights\b", r"\blocked\b", r"\bblue screen", r"\bbsod\b", r"\bspill",
             r"\bcrack", r"\bblack\b", r"\bshuts? off", r"\bturned off\b", r"\bcan'?t log ?in\b", r"\bcan'?t sign in\b",
             r"\bautomatic repair\b", r"\bbitlocker\b", r"\bknocked\b", r"\bdropped\b"]


class OfflineTriager:
    name = "offline"

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    def triage(self, text: str) -> Triage:
        t = text.lower()
        flags = {
            "safety_flag": _any(SAFETY, t),
            "security_incident": _any(SECURITY, t),
            "wants_human": _any(WANTS_HUMAN, t),
            "data_loss_risk": _any(DATA_LOSS, t),
            "already_tried": _any(ALREADY_TRIED, t),
            "multi_user": _any(MULTI_USER, t),
            "needs_specialist": _any(SPECIALIST, t),
        }

        # Category = the category whose articles retrieval ranks highest, weighted by score.
        cat_scores: dict[str, float] = defaultdict(float)
        for hit in self.retriever.search_articles(text, k=5):
            cat_scores[hit.chunk.category] += hit.score
        ranked = sorted(cat_scores.items(), key=lambda kv: kv[1], reverse=True)
        if ranked:
            category, top = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else 0.0
            margin = (top - second) / top if top > 0 else 0.0
            strength = min(1.0, top / STRONG_MATCH_SCORE)
            # Confident only when the match is both strong and clearly ahead of the runner-up.
            confidence = strength * (0.4 + 0.6 * margin)
        else:
            category, confidence = "boot_os", 0.0

        # Deterministic overrides: physical damage and safety are never left to ranking alone.
        if _any(PHYSICAL, t):
            category, confidence = "physical_damage", max(confidence, 0.8)
        if flags["safety_flag"]:
            category, confidence = "safety_hazard", 1.0
        if flags["security_incident"]:
            category, confidence = "account_access", max(confidence, 0.9)

        return Triage(
            category=category,  # type: ignore[arg-type]
            urgency=self._urgency(t, flags),  # type: ignore[arg-type]
            confidence=round(min(max(confidence, 0.0), 1.0), 3),
            summary=text.strip()[:160],
            **flags,
        )

    @staticmethod
    def _urgency(t: str, flags: dict[str, bool]) -> str:
        if flags["safety_flag"] or flags["security_incident"]:
            return "critical"
        if flags["data_loss_risk"] or flags["multi_user"] or _any(CANT_WORK, t):
            return "high"
        if _any(INSTALL_REQUEST, t) or _any(HOW_TO, t):
            return "low"
        return "medium"
