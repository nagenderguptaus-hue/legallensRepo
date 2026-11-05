# End-to-end UI testing with the real AI stack: plan

Status: **plan, waiting for your green signal**. Nothing is built yet.

## 1. Goal

Drive the real UI in a browser (Playwright), with the **full AI stack** behind it (Claude
router, Ask, Summary and Draft workflows, plus AI ingestion: OCR, chunking, bge embeddings and
the Qdrant index). For each feature, check what the UI shows **and** what the backend returned
(citations, intent, outcome, stored messages).

What the current suites cover, and what's missing:

| Suite | Backend | Gap |
|---|---|---|
| `e2e/demo.spec.ts` | MSW mocks | no real backend |
| `e2e/integration.spec.ts` | real FastAPI, **stand-in** chat and ingestion | no LLM, no real retrieval, no real citations |
| **new `e2e/ai.spec.ts`** | real FastAPI + **Claude + AI ingestion** | this plan |

## 2. Setup

- New config `frontend/playwright.ai.config.ts` and script `npm run test:e2e:ai`. It starts:
  - the backend on port **8020** with `LL_ORCHESTRATOR=legallens.adapters.ai:create_orchestrator`,
    `LL_INGESTION=legallens.adapters.ai:create_ingestion`, and a **fresh temporary
    `LL_DATA_DIR`** (Q1). Your dev data in `backend/data` is never touched. Models are read
    from the shared `ai/data/models` cache, so nothing is downloaded. The API key comes from
    `ai/.env`.
  - `vite preview --mode backend` on port **4175** with a proxy to 8020. The existing suites use
    4173 and 8010/4174, so nothing collides.
- The suite runs in order (`serial`), 1 worker, Edge (as in the other configs). Timeouts are
  long (5 min per test) because CPU retrieval and Opus drafting take 10–30 s per turn.
- Documents: the synthetic fixtures the backend already builds
  (`Commercial_Lease_Agreement.pdf`, `Mutual_NDA.docx`, `Scanned_Exhibit_A.pdf`). We know their
  contents, so we can check facts and citations.
- Every test is recorded: trace, video and screenshots go into an HTML report
  (`playwright-report-ai/`), so you can watch each LLM answer.
- A helper (`e2e/ai-helpers.ts`) also calls the backend API from the test
  (`GET /api/conversations/{id}`, `GET /api/documents/{id}/pages/{n}`). It checks the
  **backend's** response, not only what the UI rendered (Q2).

## 3. How LLM answers are checked (Q2)

LLM wording changes from run to run, so tests never compare exact text. They check:

1. **Structure**: the intent badge (Ask, Summary or Draft), the article role ("Legal Lens
   response", "Document summary", "Draft legal memo"), streaming ends, and no error banner.
2. **Facts**: lenient regexes for facts that are in the document, e.g. `\$4,500` rent,
   `three \(3\) years` NDA term, `early|terminat` for termination.
3. **Citations are real**: for each citation the backend stored, the cited page exists, the
   page's text contains the quote (ignoring whitespace and "…" shortening), and the `[n]`
   markers in the text match the citation list. In the UI, clicking a chip opens the Source
   Viewer on that page with the quote highlighted (`<mark>`).
4. **Backend agrees with the UI**: the stored message has the expected `intent`, `outcome`,
   `status: complete`, and the same citation count as the chips on screen.

## 4. Test cases

### A. Conversation management (your scenarios 1–3)

| ID | Test | Checks |
|---|---|---|
| A1 | **Create** a conversation: New chat (button and Ctrl+Shift+O), send the first message | URL becomes `/c/{id}`, the sidebar shows it, the backend lists it, and it gets an automatic title when the reply finishes |
| A2 | **Rename** a conversation from the ⋯ menu | Enter saves, Esc cancels, an empty title is refused, the title survives a reload, and the backend returns the new title |
| A3 | **Delete** a conversation | Cancel keeps it. Confirming removes it from the sidebar and the backend (404). If it was open, the page goes to New chat. Its URL now shows "Conversation not found" |
| A4 | Search conversations (Ctrl+K) | Filters by title, clearing the search restores the list |

### B. Ask with citations (scenario 4)

| ID | Test | Checks |
|---|---|---|
| B1 | Setup: upload the lease PDF (AI ingestion) | The card goes from Processing (stage and progress) to Ready, the page count is right, and the composer selects it automatically |
| B2 | "Can the tenant terminate the lease early?" | Intent Ask, the answer mentions early termination, at least 1 citation, citations verified against page text (§3), the chip opens the Source Viewer with a highlight, Previous/Next page works |
| B3 | Follow-up using a pronoun: "How much notice does it require?" | Answered from the right clause, cited (tests the query rewriter) |
| B4 | "What is the monthly rent?" | `$4,500` with a citation |
| B5 | "Does the lease include a non-compete clause?" | Outcome `not_found`, "Not found in the document" card, no made-up citations |

### C. Summarize an existing document in a new conversation (scenario 5)

| ID | Test | Checks |
|---|---|---|
| C1 | New chat → choose the lease that's already uploaded in the document picker → "Summarize this document" | Intent Summary, "Document summary" article with its sections, citations verified, Copy summary works (clipboard), backend `documentId` = lease |

### D. Upload a new document, then summarize (scenario 6)

| ID | Test | Checks |
|---|---|---|
| D1 | New chat → upload `Mutual_NDA.docx` → it becomes the active document → "Summarize this NDA" | DOCX goes through AI ingestion, Summary intent, mentions the 3-year term, citations point to the NDA (not the lease) |

### E. Drafting (scenario 7)

| ID | Test | Checks |
|---|---|---|
| E1 | New chat, with the lease → "Draft a memo to the client on their options to exit the lease early" | Intent Draft, "Draft legal memo" article, memo structure (To/From/Re or headings), `[placeholders]` shown with the "need your input" note, citations verified, Copy draft works |
| E2 | Follow-up: "Make it shorter" | Still a Draft, shorter than E1 (character count), keeps citations |

### F. Other UI pieces (comprehensive)

| ID | Test | Checks |
|---|---|---|
| F1 | Vague message ("hmm") | Clarify, 3 suggestion chips, clicking one sends it and gets an answer |
| F2 | Stop generating mid-answer, then send again | "Stopped…" note, stored with status `stopped`, the next message works (no "busy" error) |
| F3 | Reload a conversation | Messages, citations and the stopped note come back from SQLite |
| F4 | Scanned PDF (`Scanned_Exhibit_A.pdf`) | With AI ingestion it should be **OCR'd and become Ready** (stand-in fails it). Ask a question about it and get a cited answer, with the OCR note in the Source Viewer |
| F5 | Duplicate upload | Toast "already in your library" |
| F6 | Non-legal or unsupported file (e.g. `.txt`) | Rejected with a clear message, nothing uploaded |
| F7 | Delete a document that a conversation used | "Source document deleted" banner, it's gone from the picker, and asking again gives "A document is needed" |
| F8 | Status and privacy | "AI model ready", "Files stay on this device · AI in the cloud" |
| F9 | Layout and shortcuts | Ctrl+B sidebar, Ctrl+. documents panel, `?` shortcuts dialog, Copy message/response |
| F10 | Unknown URL `/nope` and `/c/conv_x` | "Page not found" / "Conversation not found" with a New chat button |

## 5. Deliverables

1. `frontend/playwright.ai.config.ts`, `frontend/e2e/ai.spec.ts`, `frontend/e2e/ai-helpers.ts`,
   the `test:e2e:ai` npm script, and a 3-line README section. No app code changes.
2. A **test report** (§8 of this file, filled in after the run): pass/fail per test case, the
   actual LLM answers for the scenario tests (text plus citations), timings, API cost, and every
   bug found with steps to reproduce.
3. **Bugs**: logged with evidence, **not fixed** without asking you (Q3).

## 6. Cost and time

- Roughly 20 LLM turns per run: Haiku (router and rewriter) on every turn, Sonnet for Ask and
  Summary, Opus for 2 drafts. **About $0.50–$1.00 per full run.** I expect 2–4 runs while
  writing the tests, so about **$2–4 in total**.
- Run time is about 10–15 min (CPU retrieval and reranking, plus ingestion of 3 documents).

## 7. Questions (recommendation first)

- **Q1. Data:** (a) **fresh temporary data folder per run, the test uploads the documents
  itself** (recommended: repeatable and doesn't touch your library), or (b) run against your
  dev `backend/data` and pick documents already there.
- **Q2. Strictness:** (a) **structure + facts + citations checked against the page text**
  (recommended), or (b) also use an LLM judge to grade answer quality (adds cost and
  flakiness. I'd do it later, in the `ai/evals` harness, not in UI tests).
- **Q3. Bugs found:** (a) **report them in §8 and ask before fixing** (recommended), or
  (b) fix small UI bugs on the spot.
- **Q4. CI:** (a) **local only, run by hand** (recommended: needs an API key and models of
  about 4 GB), or (b) a manual-trigger CI job with the key as a secret.

## 8. Results

_(filled in after the run)_
