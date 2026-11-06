"""LLM paths tested with fake clients, so they run in CI with no API key and no network."""

from types import SimpleNamespace

from fixflow.agent import FixFlowAgent
from fixflow.classify import OfflineTriager
from fixflow.llm import AnthropicClient, LLMTriager, OpenAIClient, extract_json, ungrounded_steps
from fixflow.schemas import SupportRequest


class FakeClient:
    def __init__(self, payload=None, error=None,
                 answer="1. Press Windows + Ctrl + Shift + B to restart the graphics driver. [KB-004]"):
        self.payload, self.error, self.answer, self.calls = payload, error, answer, 0

    def complete_json(self, system, user, schema):
        self.calls += 1
        if self.error:
            raise self.error
        assert "Knowledge base" in user and schema["type"] == "object"
        return self.payload

    def complete_text(self, system, user):
        return self.answer


GOOD = {"category": "display", "urgency": "medium", "confidence": 0.9, "summary": "Screen flickers."}


def make(agent, client):
    return LLMTriager(client, OfflineTriager(agent.retriever), name="fake")


def test_llm_result_is_used(agent):
    triage = make(agent, FakeClient(GOOD)).triage("my screen flickers")
    assert triage.category == "display" and triage.confidence == 0.9


def test_rules_override_model_on_safety(agent):
    # The model says "display", but the text mentions smoke: safety rules must win.
    triage = make(agent, FakeClient(GOOD)).triage("screen flickers and there is smoke")
    assert triage.category == "safety_hazard" and triage.safety_flag and triage.urgency == "critical"


def test_invalid_model_output_falls_back(agent):
    triager = make(agent, FakeClient({"category": "not-a-category"}))
    triage = triager.triage("my screen flickers")
    assert triage.category == "display" and triager.last_error


def test_api_error_falls_back_and_is_traced(settings, store):
    base = FixFlowAgent(settings, store=store)
    agent = FixFlowAgent(settings, store=store, triager=make(base, FakeClient(error=TimeoutError("timed out"))))
    r = agent.handle(SupportRequest(text="screen flickering"))
    assert r.action == "self_serve" and any("failed" in s for s in r.trace)


def test_llm_writes_the_answer(settings, store):
    base = FixFlowAgent(settings, store=store)
    agent = FixFlowAgent(settings, store=store, triager=make(base, FakeClient(GOOD)))
    r = agent.handle(SupportRequest(text="my screen flickers"))
    assert r.answer.startswith("1. Press Windows + Ctrl + Shift + B to restart the graphics driver. [KB-004]")


def test_anthropic_client_reads_tool_call():
    block = SimpleNamespace(type="tool_use", input=GOOD)
    sdk = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(content=[block])))
    assert AnthropicClient("m", client=sdk).complete_json("s", "u", {"type": "object"}) == GOOD


def test_openai_client_parses_json():
    msg = SimpleNamespace(content='{"category": "display"}')
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=msg)]))))
    assert OpenAIClient("m", client=sdk).complete_json("s", "u", {}) == {"category": "display"}


def test_openai_client_retries_without_json_mode():
    calls = []

    def create(**kw):
        calls.append(kw)
        if "response_format" in kw:
            raise ValueError("response_format not supported")
        msg = SimpleNamespace(content='Sure! ```json\n{"category": "display"}\n```')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert OpenAIClient("m", client=sdk).complete_json("s", "u", {}) == {"category": "display"}
    assert len(calls) == 2


def test_extract_json():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('here you go: {"a": {"b": 2}} thanks') == {"a": {"b": 2}}


def test_groundedness_check_flags_invented_steps(agent):
    article = [h for h in agent.retriever.search("screen flickering", k=50) if h.chunk.article_id == "KB-004"]
    grounded = "1. Press Windows + Ctrl + Shift + B to restart the graphics driver.\n2. Update the graphics driver and BIOS."
    invented = grounded + "\n3. Disable hardware acceleration in Chrome settings menu."
    assert ungrounded_steps(grounded, article) == []
    assert ungrounded_steps(invented, article) == ["Disable hardware acceleration in Chrome settings menu."]


def test_ungrounded_llm_answer_is_replaced_by_article_steps(settings, store):
    base = FixFlowAgent(settings, store=store)
    invented = "1. Reinstall your operating system from a USB stick.\n2. Buy a new monitor cable online. [KB-004]"
    agent = FixFlowAgent(settings, store=store, triager=make(base, FakeClient(GOOD, answer=invented)))
    r = agent.handle(SupportRequest(text="my screen flickers"))
    assert "Windows + Ctrl + Shift + B" in r.answer and "USB stick" not in r.answer
    assert any(t.startswith("grounding:") for t in r.trace)
