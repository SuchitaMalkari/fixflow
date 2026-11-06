"""LLM-backed triage and grounded answer writing, for Anthropic (Claude) or OpenAI.

Design choices worth knowing for an interview:
- Structured output: the model must return JSON that matches the Triage schema. Anthropic does this through a
  forced tool call, OpenAI through JSON mode. Pydantic validates the result; invalid output is rejected.
- Grounding: the model only sees the retrieved knowledge-base sections and must cite their article IDs.
- Guardrails stay outside the model: the offline safety/security rules are OR-ed with the LLM's flags,
  so a model mistake can make the agent more careful but never less.
- Failure: any API or validation error falls back to the offline triager, and the trace records it.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from .classify import OfflineTriager
from .schemas import CATEGORIES, SearchHit, Triage

TRIAGE_SYSTEM = f"""You are FixFlow, the triage step of an IT-support system for laptops.
Classify the user's request using ONLY these categories: {", ".join(CATEGORIES)}.
Use the knowledge-base sections provided to decide which category fits best.
Urgency: critical = safety or security risk; high = user cannot work, data at risk, or many users affected;
low = how-to questions and routine requests; otherwise medium.
Set confidence between 0 and 1. Use a low value (below 0.35) when the request is too vague to classify.
Set each flag to true only when the text clearly supports it:
- safety_flag: swelling, smoke, burning smell, sparks, extreme heat
- security_incident: sign-ins or activity the user does not recognise, suspected hacking or phishing
- wants_human: the user asks for a person or a manager
- data_loss_risk: important data without a backup is at risk
- already_tried: the user already tried fixes or this is a repeat report
- multi_user: several people are affected
- needs_specialist: hardware fault signs or a request self-service cannot solve
Write a one-sentence neutral summary."""

ANSWER_SYSTEM = """You are FixFlow, a friendly IT-support assistant. Answer using ONLY the knowledge-base sections
provided. Give at most 5 short numbered steps, then one line saying what to do if the steps do not work.
Cite the article IDs you used in square brackets, e.g. [KB-004]. If the sections do not cover the problem,
say so in one sentence instead of guessing."""


def _triage_tool_schema() -> dict[str, Any]:
    schema = Triage.model_json_schema()
    schema.pop("title", None)
    return schema


def _context(hits: list[SearchHit]) -> str:
    return "\n\n".join(
        f"[{h.chunk.article_id}] {h.chunk.title} - {h.chunk.section}\n{h.chunk.text}" for h in hits
    )


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...
    def complete_text(self, system: str, user: str) -> str: ...


class AnthropicClient:
    def __init__(self, model: str, client: Any | None = None) -> None:
        if client is None:
            import anthropic  # imported lazily so offline mode needs no SDK

            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.client, self.model = client, model

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=600,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": "record_triage", "description": "Record the triage decision.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": "record_triage"},
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        raise ValueError("model did not return a tool call")

    def complete_text(self, system: str, user: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(b, "text", "") for b in response.content).strip()


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply, tolerating ```json fences or extra words around it."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("model reply contained no JSON object") from None
        return json.loads(match.group(0))


class OpenAIClient:
    """Works with OpenAI and with OpenAI-compatible providers (for example Groq or Gemini) via OPENAI_BASE_URL."""

    def __init__(self, model: str, client: Any | None = None) -> None:
        if client is None:
            import openai

            client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.client, self.model = client, model

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system + "\nReply with ONLY a JSON object matching this schema:\n" + json.dumps(schema)},
            {"role": "user", "content": user},
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model, temperature=0, response_format={"type": "json_object"}, messages=messages,
            )
        except Exception:
            # Some OpenAI-compatible providers do not support JSON mode: ask again without it.
            response = self.client.chat.completions.create(model=self.model, temperature=0, messages=messages)
        return extract_json(response.choices[0].message.content)

    def complete_text(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return (response.choices[0].message.content or "").strip()


_GUARDRAIL_FLAGS = ("safety_flag", "security_incident", "wants_human", "data_loss_risk")


class LLMTriager:
    def __init__(self, client: LLMClient, fallback: OfflineTriager, name: str = "llm") -> None:
        self.client, self.fallback, self.name = client, fallback, name
        self.last_error: str | None = None

    def triage(self, text: str) -> Triage:
        self.last_error = None
        rules = self.fallback.triage(text)
        hits = self.fallback.retriever.search_articles(text, k=4)
        user = f"Knowledge base:\n{_context(hits)}\n\nUser request:\n{text}"
        try:
            result = Triage.model_validate(self.client.complete_json(TRIAGE_SYSTEM, user, _triage_tool_schema()))
        except Exception as exc:  # API down, bad key, invalid JSON: degrade instead of failing the request
            self.last_error = f"{type(exc).__name__}: {exc}"
            return rules
        # Rules can only add caution on top of the model.
        updates = {flag: getattr(result, flag) or getattr(rules, flag) for flag in _GUARDRAIL_FLAGS}
        if rules.safety_flag:
            updates |= {"category": "safety_hazard", "urgency": "critical", "confidence": 1.0}
        return result.model_copy(update=updates)

    def write_answer(self, text: str, hits: list[SearchHit]) -> str | None:
        try:
            return self.client.complete_text(ANSWER_SYSTEM, f"Knowledge base:\n{_context(hits)}\n\nUser request:\n{text}")
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None


def build_client(provider: str, model: str) -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(model)
    if provider == "openai":
        return OpenAIClient(model)
    raise ValueError(f"unknown provider '{provider}' (use offline, anthropic or openai)")
