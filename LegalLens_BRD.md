# Legal Lens — Requirements Document (BRD / PRD / FRD)

| | |
|---|---|
| **Version** | 1.1 (intent router, OCR, LangChain, SSE) |
| **Date** | October 2, 2026 |
| **Status** | Final (baseline for technical architecture) |
| **Source** | [ideas.md](ideas.md) |
| **Purpose** | Class demonstration project, built to production-grade standards |

---

## 1. Overview

### 1.1 Problem
Solo lawyers spend a lot of unbillable time reading long documents, finding specific clauses and drafting routine memos. General-purpose chatbots often answer from general knowledge instead of the lawyer's own documents, rarely show where an answer came from, and can invent facts or citations. In legal work, any of these is unacceptable.

### 1.2 Solution
**Legal Lens** is an AI assistant that runs **entirely on the lawyer's own machine**, including the AI models, so client documents never leave it. The lawyer uploads documents and uses three features:

- **Ask:** questions answered **only** from the uploaded documents, with citations to the source.
- **Summary:** a structured summary of a document.
- **Draft:** a first draft of a legal memo or case brief, built from instructions and a reference document.

It is built as a **RAG (Retrieval-Augmented Generation)** application. The app first finds the most relevant passages in the user's documents, then has the AI model answer using only those passages.

### 1.3 Goals
| # | Goal |
|---|------|
| G1 | Answers come only from the user's documents, and each answer cites its source. |
| G2 | Cut the time it takes to understand a document or produce a first draft. |
| G3 | Show students a complete, production-grade AI application: three layers, tests, CI, logging and AI evaluation. |
| G4 | The AI model and vector store can be swapped without changes to the rest of the system. |
| G5 | Full privacy: all processing is local, and the app works **offline** after setup. |

---

## 2. Users and Scope

### 2.1 Persona
**Maya, a solo practitioner.** She handles a mix of matters (contracts, disputes, advisory work) with no support staff and works on her own laptop. She cares most about client confidentiality, being able to check answers against the source, and saving time. She is comfortable with technology but is not a developer.

### 2.2 User Stories
| ID | As a solo lawyer, I want to… | So that… |
|----|------------------------------|----------|
| US-1 | upload a PDF or Word document | I can work with it in Legal Lens. |
| US-2 | ask about a document and see the cited passage | I can check the answer before relying on it. |
| US-3 | be told when the document doesn't contain the answer | I'm never misled by a guess. |
| US-4 | get a structured summary of a long document | I understand it in minutes, not hours. |
| US-5 | draft a memo from my instructions and a reference document | I start from a solid first draft. |
| US-6 | come back later and find my documents and past chats | I don't have to repeat my work. |
| US-7 | delete a document and everything derived from it | I stay in control of client data. |

### 2.3 Scope
| In scope (v1) | Out of scope (v1, possible later) |
|---------------|-----------------------------------|
| Upload, list and delete PDF/DOCX files, digital **or scanned** (layout analysis + OCR) | Other file types (images, email, spreadsheets) |
| Ask with citations, on one selected document | Questions across several documents, comparing documents |
| Structured Summary | Summaries tailored to a jurisdiction or practice area |
| Draft: legal memo, case brief, free-form | Templates, editing drafts in the app, DOCX/PDF export |
| Chat history saved locally | Sync across devices, sharing |
| Single user on localhost, local AI models | Login, multiple users, cloud hosting, cloud AI APIs |
| RAG pipeline | Outside legal research (case law, statutes, web), multi-agent workflows |

Legal Lens does **not** give legal advice. Everything it produces is a draft for a lawyer to review.

---

## 3. Functional Requirements

Priority: **M** = Must have for v1 · **S** = Should have (include if time allows).

### 3.1 Document Management
| ID | Requirement | Pri |
|----|-------------|-----|
| FR-1 | Upload a **PDF (digital or scanned) or DOCX** file by drag-and-drop or file picker. | M |
| FR-2 | Reject unsupported, empty, password-protected or oversized files (NFR-3) with a clear message. | M |
| FR-3 | Process each upload: check each page for a text layer → **layout parsing** (digital pages) or **OCR + layout detection** (scanned pages) → quality check → chunk → embed → index. Show the status *Processing → Ready / Failed*, plus warnings such as low OCR confidence. | M |
| FR-4 | A **document library** shows each document's name, type, page count, upload date and status. Documents remain after the app restarts. | M |
| FR-5 | **Deleting** a document removes the file, its extracted text, its embeddings and its index entries. | M |

### 3.2 Ask
| ID | Requirement | Pri |
|----|-------------|-----|
| FR-6 | Select **one Ready document** and ask a question in natural language from the prompt bar. | M |
| FR-7 | Answers are based **only** on passages retrieved from that document, never on outside legal knowledge. | M |
| FR-8 | Every answer includes **citations**: the page (PDF) or section/paragraph (DOCX) plus a short excerpt, which can be expanded to show the full passage. | M |
| FR-9 | If the retrieved passages don't support an answer, reply *"I couldn't find this in the document"* instead of guessing. | M |
| FR-10 | Follow-up questions keep the conversation's context. | M |
| FR-11 | Answers stream in as they are generated. | S |

### 3.3 Summary
| ID | Requirement | Pri |
|----|-------------|-----|
| FR-12 | Summarize a selected Ready document using a fixed structure: **Document type & purpose · Parties · Key dates & deadlines · Key terms / obligations / holdings · Notable risks · Plain-language overview**. | M |
| FR-13 | Each section cites the pages or sections it is based on. A section that doesn't apply shows "Not found in document". | M |
| FR-14 | A document longer than the model's context window is summarized in stages: each part separately, then the results combined. A progress indicator is shown. | M |

### 3.4 Draft
| ID | Requirement | Pri |
|----|-------------|-----|
| FR-15 | The user asks for a **Legal memo** or **Case brief** in plain language (the draft type is inferred from the prompt) and can optionally select one reference document. | M |
| FR-16 | **Free-form** drafting of any document the user describes (for example, a demand letter). | S |
| FR-17 | Facts come only from the instructions or the reference document. Unknown facts or legal citations appear as visible placeholders such as `[CITATION NEEDED]` or `[CONFIRM: date]`, never invented. | M |
| FR-18 | The draft is shown formatted in the app, with a **Copy** button. | M |

### 3.5 Conversations and General Behaviour
| ID | Requirement | Pri |
|----|-------------|-----|
| FR-19 | Every Ask, Summary or Draft interaction is saved in a **conversation**, linked to the documents it used. | M |
| FR-20 | List, reopen and continue, rename or delete past conversations. | M |
| FR-21 | If a document is deleted, the conversations that used it remain and are marked "source document deleted". | S |
| FR-22 | There is no mode selector. An **LLM intent router** classifies every message as *ask*, *summary* or *draft*, and the UI shows the detected intent as a badge. If the intent is unclear (*clarify*), the assistant asks a follow-up question. Ask and Summary prompt the user to upload or select a document if none is Ready. | M |
| FR-23 | A disclaimer is always visible: *"AI-generated content. Not legal advice. Review before use."* | M |
| FR-24 | Every error shows a clear message and a next step (for example, "Model unavailable — check that the model runtime is running"). | M |

---

## 4. Non-Functional Requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | **Performance** | On the reference machine: a 50-page digital PDF is *Ready* in **≤ 90 s**, and a scanned one (OCR) in **≤ 5 min**. Ask shows the first text in **≤ 10 s** and finishes in **≤ 60 s**. A 50-page Summary takes **≤ 5 min**. CPU-only machines are supported but may be 2–4× slower. |
| NFR-2 | **Hardware** | Minimum: **16 GB RAM** and **15 GB free disk**, on Windows, macOS or Linux. Reference machine: Apple Silicon, or a GPU with **≥ 8 GB VRAM**. |
| NFR-3 | **Limits** | Each file: **≤ 25 MB** and **≤ 300 pages**. Library: **≤ 100 documents**. All limits can be changed in configuration. |
| NFR-4 | **Privacy** | Documents, embeddings, chat history **and all AI processing** stay on the local machine. After the models are downloaded, the app makes **no outbound network calls**. |
| NFR-5 | **Security** | The backend and the model runtime bind to `127.0.0.1` only. Uploads are checked by file content, not just by extension. `.env` is never committed. Logs contain IDs and metadata only, never document text or prompts. |
| NFR-6 | **AI safety** | Document text is treated as **data, never as instructions**, to defend against prompt injection. Answers in Ask must be cited (FR-7, FR-8), and drafts use placeholders instead of invented citations (FR-17). |
| NFR-7 | **Modularity** | The LLM, the embedding model and the vector store each sit behind an interface. Switching local models is a configuration change, and a new runtime needs only one adapter class. |
| NFR-8 | **Reliability** | Nothing is left half-processed: a failed document shows *Failed* and can be retried or deleted. Model calls have timeouts and a limited number of retries. |
| NFR-9 | **Usability** | Core flows work with the keyboard alone. Contrast meets WCAG 2.1 AA. Any action that takes longer than 1 s shows a loading or progress state. |
| NFR-10 | **Observability** | Structured JSON logs with a request ID on every call. Timings are recorded for each step (retrieval, generation). |
| NFR-11 | **Setup** | One command (Docker Compose or a script) starts the frontend, the backend and the model runtime, and downloads the models on first run. A new user is running within **15 min** by following the README, not counting the model download. |
| NFR-12 | **Maintainability** | Typed code (Python type hints, TypeScript), with automatic linting and formatting. Python dependencies are managed with **uv** and pinned in a lock file. |

---

## 5. Solution Overview

### 5.1 Architecture

```
┌──────────────────────┐   REST/JSON (streamed)  ┌──────────────────────┐
│ Frontend (Phase 1)   │ ──────────────────────► │ Backend (Phase 2)    │
│ React + Vite         │ ◄────────────────────── │ FastAPI + uv         │
│ Library · Prompt bar │                         │ API · validation ·   │
│ Sidebar · Chat · Cite│                         │ storage · history    │
└──────────────────────┘                         └──────────┬───────────┘
                                                            │
                                                 ┌──────────▼───────────┐
                                                 │ AI Layer (Phase 3)   │
                                                 │ Ingest: extract →    │
                                                 │  chunk → embed → index│
                                                 │ Query: retrieve →    │
                                                 │  prompt → LLM → cite │
                                                 └──────────┬───────────┘
                             ┌──────────────────────────────┼──────────────────┐
                             ▼                              ▼                  ▼
                    File store + metadata DB      Local vector store   Local LLM + embeddings
              ── all components run on the lawyer's machine (localhost) ──
```

### 5.2 RAG Flow
The full flow diagram is in [architecture/legal_lens_flow.excalidraw](architecture/legal_lens_flow.excalidraw).
1. **Ingest** (once per document): validate → check each page for a text layer → layout parsing or OCR → quality check → clean → structure-aware parent/child chunking → embed into the vector store and add to the BM25 index (SQLite FTS5).
2. **Route:** load the conversation context → input guard → an **LLM intent router** sends the request to the Ask, Summary or Draft workflow.
3. **Retrieve** (Ask and Draft): the **query editor** rewrites the follow-up into a standalone query using chat history, plus 3 variants → **hybrid search** (vector + BM25) → Reciprocal Rank Fusion → cross-encoder re-rank → context builder.
4. **Generate:** the LLM answers or drafts using only the retrieved context, with inline citations. Summary uses section-by-section map-reduce instead of retrieval.
5. **Verify & respond:** a sufficiency gate, a citation verifier and a placeholder guard check the output → it streams to the UI over SSE → the turn is saved to SQLite.

### 5.3 Technology Decisions
| Area | Decision | Status |
|------|----------|--------|
| Frontend | React + Vite, TypeScript | Decided |
| Backend | Python 3.12+, FastAPI, uv | Decided |
| Streaming | Server-Sent Events (`POST /api/chat/stream`) | Decided |
| Orchestration | LangChain (LCEL chains, branching by intent) | Decided |
| Model hosting | Local only, through a local model runtime (e.g. Ollama) | Decided |
| Conversations, transactions, BM25 index | SQLite (with FTS5 for keyword search) | Decided |
| LLM, embedding model, vector store | Local and behind interfaces, chosen to fit NFR-1 and NFR-2 | Deferred to architecture |
| RAG tuning (chunk size, top-k, re-ranking) | Tuned against the evaluation set (§6) | Deferred to architecture |

---

## 6. Quality, Testing and Evaluation

| Area | What we do |
|------|------------|
| **Automated tests** | Backend: pytest unit tests (parsing, chunking, citation checks, validation) and integration tests of the upload → ask flow using a **mock LLM**. Frontend: component tests for upload, the conversation sidebar, SSE streaming and citations. The evaluation set also checks intent routing. |
| **CI** | GitHub Actions runs lint, type checks and tests on every push and pull request. A pull request can only be merged when CI is green. |
| **AI evaluation set** | 3–5 public-domain documents (e.g. an NDA, a lease, a court opinion) with **30–50 questions**, each with an expected answer and source page. The set includes **unanswerable** and **prompt-injection** cases, and a script runs it and reports the scores. |
| **AI quality targets** | Answer correctness **≥ 80%** · correct citation **≥ 90%** · correct "not found" on unanswerable questions **≥ 90%** · **zero** invented citations in drafts. |
| **Errors** | The API returns errors in one JSON format (`code`, `message`, `request_id`), and the UI turns them into clear messages (FR-24). |

---

## 7. Success Criteria (Demo Acceptance)

On a clean machine:
1. One-command setup works by following the README (NFR-11).
2. The live demo runs end to end: upload → Ask with clickable citations → an unanswerable question correctly refused → Summary → Draft a memo with placeholders → restart the app and reopen the conversation → delete the document.
3. The same demo works **with the network disconnected** (NFR-4).
4. CI is green, and the evaluation report meets the targets in §6.
5. Switching to a different local model needs only a configuration change (NFR-7).

---

## 8. Assumptions, Risks and Open Items

**Assumptions:** one user on one machine with no login · documents are in English · demo documents are public or synthetic, never real client data · "draft a legal case" means case documents, starting with a case brief · the limits and targets in NFR-1, NFR-3 and §6 are accepted for v1.

| Risk | Mitigation |
|------|------------|
| Hallucinated answers or citations | Prompts that allow only document text, checking every citation against the retrieved chunks, "not found" behaviour, the evaluation set |
| Local model too slow or too weak on student laptops | A small quantized model chosen against the evaluation set, streaming and progress indicators, and running the live demo on the reference machine |
| Poor extraction or OCR (tables, multi-column layouts, low-quality scans) | Layout detection, OCR confidence checks with warnings, and varied sample documents (including scans) in the evaluation set |
| Intent router picks the wrong workflow | The intent badge is visible to the user, a *clarify* fallback handles unclear requests, and routing cases are included in the evaluation set |
| Prompt injection inside a document | Document text treated as data (NFR-6), with injection cases in the evaluation set |

| # | Open item | Needed by |
|---|-----------|-----------|
| 1 | Specific local LLM, embedding model, vector store and runtime, then a check against NFR-1 | Technical architecture |
| 2 | RAG tuning details (chunk size, top-k, re-ranking) | Technical architecture |
| 3 | Compliance stance (GDPR, ABA guidance on AI). Informational for a demo. | Before any real-world use |

---

## 9. Delivery Phases

| Phase | Deliverable | Done when |
|-------|-------------|-----------|
| 0 | This document + technical architecture | Open items 1–2 resolved |
| 1 | **Frontend:** conversation sidebar, documents panel, prompt bar, streaming chat and citation views, running against a mock API | Component tests pass, and the UI flows can be demoed |
| 2 | **Backend:** FastAPI endpoints, validation, storage, history, logging, CI | Integration tests pass using a mock LLM |
| 3 | **AI layer:** ingestion, RAG pipeline, Ask/Summary/Draft prompts, citation checks, evaluation script | The §6 targets are met and the §7 demo passes |
| Future | Multi-document Q&A, draft export, multi-agent workflows | — |
