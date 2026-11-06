# FixFlow walkthrough and interview prep

Read this before you push, and again before any interview. If you can't explain a part of this project, don't claim it.

## The 60-second pitch

> "FixFlow is an AI agent for IT-support triage. A user describes a problem in plain language. FixFlow finds the
> right troubleshooting article using retrieval I built from scratch with BM25, classifies the request with an LLM
> that has to return validated JSON, checks the device warranty, and then decides: answer it, open a ticket for the
> right team, or escalate to a person. Safety and security rules sit outside the model, so the LLM can make it more
> careful but never less. I built an evaluation set of 50 labeled tickets, held 30 of them out, and it routes 100% of
> those correctly with every safety case escalated. CI fails the build if accuracy drops. I also exposed the
> tools as an MCP server, so Claude Desktop can check warranties and open tickets through it."

## How a request flows (agent.py `handle`)

1. **Retrieve:** `Retriever.search_articles` ranks knowledge-base sections with BM25 and keeps the best section per article.
2. **Triage:** the triager returns a `Triage` object (category, urgency, confidence, flags).
   - Offline: category from retrieval scores; flags from regex rules in `classify.py`.
   - LLM: the model fills the same schema; then `LLMTriager` ORs in the rule flags (guardrails).
3. **Check warranty:** if a serial is given, look it up in SQLite.
4. **Decide:** `decide()` checks reasons in priority order: safety → security → wants human → data at risk → low confidence → (ticket reasons) → self-serve.
5. **Act:** create a ticket or escalation in SQLite.
6. **Explain:** build the answer (LLM-written or the article's steps), add warranty notes, and return `Resolution` with `reasons` and `trace`.

## Concepts you must be able to explain

**RAG (retrieval-augmented generation).** Instead of trusting the model's memory, you retrieve relevant documents and give them to the model as context, then ask it to answer from them and cite them. This reduces made-up answers and lets you update knowledge without retraining.

**BM25.** A ranking formula: a document scores higher when it contains the query's words often (term frequency, which saturates through `k1`), when those words are rare across all documents (IDF), and it is normalised for length (`b`). Open `retrieval.py` and be ready to walk through `BM25.scores`.

**Inverted index.** A map from each word to the documents that contain it, so search only looks at relevant documents instead of all of them.

**Why BM25 and not a vector DB?** About 40 short sections, exact technical terms (BIOS, BitLocker, VPN), no infrastructure, fully explainable. Weakness: no semantic matching ("dies" vs "drains"). Fix: hybrid search with embeddings. That's on the roadmap.

**Structured outputs.** The model must return JSON matching a schema. On Anthropic it's a forced tool call (`tool_choice`), on OpenAI it's JSON mode. Pydantic validates it; invalid output triggers the fallback.

**Agents vs workflows.** In a workflow, code controls the steps and the LLM handles individual steps. In an agent, the LLM chooses its own steps. FixFlow uses a workflow because routing decisions must be predictable, testable and auditable (Anthropic's "Building effective agents" recommends starting with the simplest pattern that works).

**MCP (Model Context Protocol).** A standard way to give AI apps access to tools and data. `mcp_server.py` registers five tools; any MCP client can discover and call them. It reuses the same agent and database code as the API.

**Evals.** You can't improve what you don't measure. The dev set is for tuning, the test set is held out to estimate real performance. Tuning on the test set makes the numbers look better than reality (overfitting / data leakage).

## Questions an interviewer will likely ask

**"How did you get 100% on the test set? That sounds too good."**
It's 30 synthetic tickets I wrote myself, so it's a sanity check, not a benchmark. I kept the test set untouched while tuning and only used the dev set. The category accuracy is 90%, and the README lists the three misses. The action can still be right when the category is wrong. For example, "pc not working" is vague, so the agent escalates it because confidence is low.

**"What happens if the LLM API goes down?"**
`LLMTriager` catches any exception and falls back to the offline triager, and the trace records that. There's a test for it (`test_api_error_falls_back_and_is_traced`).

**"How do you stop the model from closing a dangerous case?"**
Safety and security detection is deterministic and runs on every request. Its flags are OR-ed with the model's output, and safety always forces escalation. Test: `test_rules_override_model_on_safety`.

**"Did the LLM ever do something you didn't expect?"**
Yes. When I turned on the live LLM, I tested it and saw it add two troubleshooting steps that weren't in the help article, even though the prompt said to use only the article. So I added a groundedness check: each numbered step is compared with the article's words, and if a step isn't supported, FixFlow throws away the LLM reply and uses the article's steps instead, and logs it in the trace. It's a simple heuristic, so it can miss subtle cases. The next step would be an LLM-as-judge check or citing sentence-level sources.

**"How would you scale this?"**
Swap SQLite for Postgres, run the API behind a load balancer with several workers, cache retrieval, move to hybrid search with a vector index once the knowledge base grows, and log every resolution to build more eval data.

**"What would you improve next?"**
Hybrid retrieval to fix the vocabulary-mismatch misses, LLM-as-judge for answer quality, and a feedback loop that adds real failures to the eval set.

**"How did you choose the confidence threshold?"**
I swept it on the dev set. Every value from 0.20 to 0.40 gave the same results, and from 0.45 up it started escalating clear requests (escalation precision fell to 75%). I picked 0.35, near the top of the safe range, to lean cautious. The dev set has few vague tickets, so it can't pin down the lower bound well. In production I'd tune it on real data, trading off escalation precision against recall.

**"Walk me through one improvement you made using the evals."**
Baseline v1 indexed only the chunk text with plain tokens. On dev, it missed "Can you install Adobe Illustrator" and "screen flickering" because the confidence was too low. v2 added light stemming and indexed the article title with each chunk. Then dev ticket T012 ("I spilled coffee") still missed the liquid-damage article, so I added one synonym rule for it. Held-out test results: action accuracy went from 96.7% to 100%, team accuracy from 86.7% to 93.3%, and escalation precision from 85.7% to 100%.

## How to demo in 3 minutes

1. `python -m fixflow "The bottom of my laptop is bulging" --trace`: shows a safety escalation and the trace.
2. `python -m fixflow "I dropped my laptop and the screen cracked" --serial PF3K9X21`: a ticket with a warranty note.
3. `python -m fixflow "pc not working"`: shows it won't guess.
4. Open `http://localhost:8000/docs` and run `/triage`.
5. `python -m fixflow.evals --compare`: shows the numbers.
6. In Claude Desktop, ask it to check a warranty through the MCP server.

## Before you push: checklist

- [ ] Run everything once on your laptop: `pytest -q`, `python -m fixflow.evals --compare`, `uvicorn fixflow.api:app`
- [ ] Replace `YOUR_GITHUB_USERNAME` in README.md (2 badge links + the clone URL)
- [ ] If you have an API key, run `FIXFLOW_PROVIDER=anthropic python -m fixflow.evals --compare` and add those numbers to the README
- [ ] Read every file once, and `retrieval.py` and `agent.py` twice
- [ ] Check that the GitHub Actions run is green after pushing
