"""The FixFlow agent: retrieve -> triage -> look up the device -> decide -> act -> explain.

This follows the "workflow" pattern from Anthropic's "Building effective agents": the LLM does the parts
that need language understanding (classifying, writing the answer), while the control flow that decides
who handles a request is plain, testable code. Every step is written to `trace` so decisions can be audited.
"""

from __future__ import annotations

from .catalog import SoftwareCatalog
from .classify import OfflineTriager
from .config import Settings
from .kb import article_steps, load_kb
from .llm import LLMTriager, build_client
from .retrieval import Retriever
from .schemas import CATEGORY_TO_TEAM, Resolution, SearchHit, SupportRequest, Triage
from .tools import Store


class FixFlowAgent:
    def __init__(self, settings: Settings | None = None, store: Store | None = None,
                 retriever_version: str = "v2", triager=None) -> None:
        self.settings = settings or Settings()
        self.chunks = load_kb(self.settings.kb_dir)
        self.retriever = Retriever(self.chunks, version=retriever_version)
        self.store = store or Store(self.settings.db_path, self.settings.devices_csv)
        self.catalog = SoftwareCatalog(self.settings.data_dir / "software_catalog.csv")
        offline = OfflineTriager(self.retriever)
        if triager is not None:
            self.triager = triager
        elif self.settings.provider == "offline":
            self.triager = offline
        else:
            client = build_client(self.settings.provider, self.settings.resolved_model())
            self.triager = LLMTriager(client, offline, name=self.settings.provider)

    # ---- decision policy ---------------------------------------------------------------------------

    def decide(self, request: SupportRequest, triage: Triage) -> tuple[str, list[str]]:
        """Return (action, reasons). Order matters: the most serious reason wins."""
        threshold = self.settings.confidence_threshold
        if triage.safety_flag or triage.category == "safety_hazard":
            return "escalate", ["Possible safety hazard: always handled by a person."]
        if triage.security_incident:
            return "escalate", ["Possible account compromise: security incidents go to a person immediately."]
        if triage.wants_human:
            return "escalate", ["The user asked for a person."]
        if triage.data_loss_risk:
            return "escalate", ["Unbacked-up data is at risk: a specialist should guide recovery before any reset."]
        if triage.confidence < threshold:
            return "escalate", [f"Low confidence ({triage.confidence:.2f} < {threshold:.2f}): not guessing."]

        reasons: list[str] = []
        if triage.category == "physical_damage":
            reasons.append("Physical damage needs a technician.")
        if triage.already_tried:
            reasons.append("The user already tried the standard fixes or reported this before.")
        if triage.multi_user:
            reasons.append("Several people are affected, which points to an outage.")
        if triage.needs_specialist:
            reasons.append("The symptoms point to a fault self-service cannot fix.")
        if triage.category == "software" and self._is_unapproved_software_request(request.text):
            reasons.append("Requested software is not in the approved catalog, so it needs a reviewed request.")
        if reasons:
            return "ticket", reasons
        return "self_serve", ["A knowledge-base article covers this and no escalation signals were found."]

    def _is_unapproved_software_request(self, text: str) -> bool:
        lowered = text.lower()
        asks_install = any(w in lowered for w in ("install", "get ", "need ", "licen"))
        is_activation_issue = any(w in lowered for w in ("activate", "unlicensed", "activation", "crash", "error"))
        return asks_install and not is_activation_issue and not self.catalog.find_in_text(text)

    # ---- main entry point --------------------------------------------------------------------------

    def handle(self, request: SupportRequest) -> Resolution:
        trace: list[str] = []
        hits = self.retriever.search_articles(request.text, k=self.settings.top_k)
        trace.append("retrieve: " + ", ".join(f"{h.chunk.article_id} ({h.score:.2f})" for h in hits))

        triage = self.triager.triage(request.text)
        error = getattr(self.triager, "last_error", None)
        if error:
            trace.append(f"triage: {self.triager.name} failed, used offline rules ({error})")
        trace.append(
            f"triage[{self.triager.name}]: category={triage.category} urgency={triage.urgency} "
            f"confidence={triage.confidence:.2f}"
        )

        # Make sure the answer cites an article from the predicted category when one was retrieved.
        same_cat = [h for h in hits if h.chunk.category == triage.category]
        if not same_cat:
            same_cat = [h for h in self.retriever.search_articles(request.text, k=12)
                        if h.chunk.category == triage.category][:1]
        cited = (same_cat or hits)[:1]

        warranty = None
        if request.serial:
            warranty = self.store.check_warranty(request.serial)
            trace.append(f"check_warranty: {warranty.model_dump() if warranty else 'serial not found'}")

        action, reasons = self.decide(request, triage)
        team = CATEGORY_TO_TEAM[triage.category]
        trace.append(f"decide: {action} -> {team} ({'; '.join(reasons)})")

        ticket_id = None
        if action == "escalate":
            ticket = self.store.escalate_to_human(
                reason=reasons[0], urgency=triage.urgency, request_text=request.text,
                serial=request.serial, category=triage.category,
            )
            ticket_id = ticket.id
            if triage.category == "safety_hazard":
                team = "safety_response"
        elif action == "ticket":
            ticket = self.store.create_ticket(
                team=team, category=triage.category, urgency=triage.urgency,
                summary=triage.summary or request.text, request_text=request.text, serial=request.serial,
            )
            ticket_id = ticket.id
        trace.append(f"act: {'ticket ' + ticket_id if ticket_id else 'no ticket needed'}")

        self._grounding_note = None
        answer = self._answer(request, action, cited, warranty, ticket_id, team)
        if self._grounding_note:
            trace.append(f"grounding: LLM reply rejected ({self._grounding_note}), used the article's own steps")
        self.store.log_request(
            text=request.text, serial=request.serial, action=action, category=triage.category, team=team,
            urgency=triage.urgency, confidence=triage.confidence, ticket_id=ticket_id,
            reasons=reasons, trace=trace,
        )
        return Resolution(
            action=action, category=triage.category, team=team, urgency=triage.urgency,  # type: ignore[arg-type]
            confidence=triage.confidence, answer=answer,
            citations=[h.chunk.article_id for h in cited], ticket_id=ticket_id,
            warranty=warranty, reasons=reasons, trace=trace,
        )

    def _answer(self, request, action, cited, warranty, ticket_id, team) -> str:
        parts: list[str] = []
        if action == "escalate":
            parts.append(f"I've passed this to a support specialist (ticket {ticket_id}). Someone will contact you directly.")
            if cited and cited[0].chunk.category == "safety_hazard":
                parts.append(article_steps(self.chunks, cited[0].chunk.article_id))
        else:
            written = None
            if isinstance(self.triager, LLMTriager) and cited:
                # Give the model the whole cited article, so the groundedness check compares against all of it.
                article = [SearchHit(chunk=c, score=0.0) for c in self.chunks if c.article_id == cited[0].chunk.article_id]
                written = self.triager.write_answer(request.text, article or cited)
                if written is None and getattr(self.triager, "last_grounding_issue", None):
                    self._grounding_note = self.triager.last_grounding_issue
            if written:
                parts.append(written)
            elif cited:
                art = cited[0].chunk
                parts.append(f"Try these steps from {art.article_id} ({art.title}):\n"
                             + article_steps(self.chunks, art.article_id))
            if action == "ticket":
                parts.append(f"I've opened ticket {ticket_id} for the {team.replace('_', ' ')} team.")
        if warranty:
            if not warranty.in_warranty:
                parts.append(f"Note: your {warranty.model} warranty ended on {warranty.warranty_end}, so repairs are paid.")
            elif action != "self_serve":
                cover = "accidental damage is covered" if warranty.covers_accidental_damage else "accidental damage is not covered"
                parts.append(f"Your {warranty.model} is under warranty until {warranty.warranty_end} ({warranty.plan} plan; {cover}).")
        return "\n\n".join(p for p in parts if p)
