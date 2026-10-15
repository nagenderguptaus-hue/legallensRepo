# AI layer — Phase 3a: Orchestrator (intent routing)

Scope: a standalone package (`ai/`, `legallens_ai`) that takes one chat message (plus recent
history) and decides which workflow should handle it. **Not wired into the backend yet**, and
no Ask/Summary/Draft workflows yet. Those come after this layer is tested.

## Decisions (please review)

| # | Decision | Why | Alternative |
|---|----------|-----|-------------|
| D1 | **Claude Haiku 4.5** (`claude-haiku-4-5`) classifies intent, through `langchain-anthropic`'s `ChatAnthropic`. Model id is config (`LL_AI_INTENT_MODEL`). | You asked for Haiku: classification is a small, latency-sensitive task. | — |
| D2 | ⚠️ **This deviates from the BRD.** BRD G5 / NFR-4 say all AI runs locally with no outbound calls. With Claude, the user's message and the last few turns are sent to Anthropic's API. Document text is **not** sent by the classifier. | Your call ("build this project with Claude models"). Recorded so it is a conscious change, not a silent one. | Keep the model behind LangChain's `BaseChatModel` so a local model can be swapped in later (NFR-7). |
| D3 | Intents are the backend contract's four: `ask`, `summary`, `draft`, `clarify` (FR-22, `ports/orchestrator.py`, `frontend/src/api/types.ts`). | Changing names would break the API contract. `clarify` is the BRD's fallback for unclear messages. | — |
| D4 | **Native structured outputs** (`with_structured_output(..., method="json_schema")`). The model can only return `{rationale, intent}` with `intent` from the enum. | The output is constrained by the API instead of parsed from free text, so no "almost valid" labels. | Forced tool calling (LangChain's default). It works on Haiku but is not schema-guaranteed. |
| D5 | `rationale` (one sentence) comes **before** `intent` in the schema. | A short reason before the label improves accuracy on edge cases and makes eval failures easy to debug. Costs ~30 output tokens. | Label only: slightly faster, harder to debug. |
| D6 | `temperature=0`, `max_tokens=512`, timeout 15 s, 2 retries. No extended thinking. | Repeatable labels; Haiku is fast enough without thinking for a 4-way choice. | — |
| D7 | The classifier sees: the **current message** and the **last 6 turns** of history (each cut to 600 characters; assistant turns carry their intent). It does **not** see whether a document is selected. | History is needed for follow-ups ("make it shorter" after a draft). Document presence would bias the label; it is handled by a plain rule instead (D8). | — |
| D8 | Deterministic rule after the model: `ask` / `summary` with no document → `needs_document = true`. `draft` works without one (FR-15). | Matches FR-22 and the backend's `needs_document` outcome. Rules that don't need an LLM shouldn't use one. | — |
| D9 | Failures **raise** typed errors (`model_unavailable`, `model_auth_failed`, `intent_unparseable`). No silent fallback to `clarify` or to the keyword rules. | A hidden fallback would mask outages and skew eval results. The backend already maps these to 503 / 502. | Fall back to `clarify` on failure. |
| D10 | Domain knowledge lives in **`src/legallens_ai/prompts/intent_classifier.prompt.md`**, loaded verbatim as the system prompt. Message and history go in the user turn inside XML tags, `<`/`>` escaped. | One file a subject-matter expert can edit without touching code. Escaping stops a message from closing its own tag. | — |
| D11 | Logs carry metadata only (intent, latency, token counts, model). Never message text (NFR-5). | — | — |
| D12 | "Summary" means the **whole document**. "Summarize the termination clause" is `ask`. | FR-12's summary is a fixed six-section template over the whole document; a narrow request is better served by retrieval. | Send every "summarize …" to Summary. |
| D13 | Mixed requests ("summarize it and draft a memo") take the **final deliverable** (`draft`). | Only one workflow runs per turn (FR-22). | `clarify` on any mixed request. |

## Plan

### Step 1 — Package skeleton ✅
- [x] `ai/` uv project, Python 3.12, `langchain-core`, `langchain-anthropic`, `pydantic`, `pydantic-settings`
- [x] Dev tools: pytest, pytest-asyncio, ruff, mypy (strict), same settings as the backend

### Step 2 — Domain prompt ✅
- [x] `intent_classifier.prompt.md`: role, the four intents, decision rules, follow-ups, edge cases, worked examples, security note

### Step 3 — Orchestrator ✅
- [x] `config.py`: `AISettings` (env prefix `LL_AI_`, reads `.env`, `ANTHROPIC_API_KEY`)
- [x] `schemas.py`: `Turn`, `DocumentInfo`, `OrchestratorRequest`, `IntentClassification`, `RoutingDecision`
- [x] `intent_classifier.py`: LCEL chain `ChatPromptTemplate | ChatAnthropic.with_structured_output(json_schema)`, error mapping
- [x] `orchestrator.py`: `Orchestrator.route()` = classify, then D8 rule

### Step 4 — Testing ✅
- [x] Unit tests with a fake model (no network, no cost)
- [x] Labelled eval set `evals/intent_cases.jsonl` (cases kept separate from the prompt's examples)
- [x] CLI: `legallens-ai classify "…"` (or interactive), `legallens-ai eval` (accuracy + confusion matrix)
- [x] Live smoke test, opt-in: `uv run pytest -m live`

### Later (not in this step)
- [x] Run the eval against real Haiku: 43/43 on 2026-10-14, no prompt change needed ([orchestration.todo.md](orchestration.todo.md))
- [x] Adapter: backend `ChatContext` → `OrchestratorRequest` (`backend/src/legallens/adapters/ai.py`, Phase 3d); the stand-in stays the default
- [x] Ask / Summary / Draft workflows behind the router: see [workflows.todo.md](workflows.todo.md)
- [ ] Prompt caching once the system prompt passes Haiku's minimum cacheable length (still ~2.2k tokens, under Haiku 4.5's 4,096: not possible yet)
- [x] CI job for `ai/` (`.github/workflows/ai.yml`)
