# Legal Lens — Ideas

> These are working notes. They collect the early thinking behind Legal Lens and come before the Business Requirements Document (BRD).

---

## 1. Vision

**Legal Lens** is an AI-powered assistant (a chatbot-style application) built for **lawyers and attorneys**. It helps legal professionals:

- ask legal questions,
- summarize legal documents, and
- draft legal content such as cases and memos.

The aim is to save attorneys time on research, reading and first drafts, and to keep answers grounded in the documents they provide.

### Decisions Made

| Topic | Decision | What it means for v1 |
|-------|----------|----------------------|
| Primary user | **A solo lawyer** | Built for one practitioner's workflow. No team or firm features. |
| Where answers come from | **Uploaded documents only** | Ask answers only from what the user uploaded. No general legal knowledge and no outside case law. |
| Users and deployment | **One person on their own machine** | Runs locally (localhost). No login, no user accounts, no separate spaces for different users. |

---

## 2. Target Users

- **Primary (v1):** a solo lawyer (single practitioner).
- **Possible future users:** small law firms, paralegals, in-house legal teams.

---

## 3. Core Features (MVP)

| Feature | Description |
|---------|-------------|
| **Ask** | The user asks questions about the documents they uploaded. Answers come **only from those documents**. If the documents don't contain the answer, Legal Lens says so instead of guessing. |
| **Summary** | The user uploads a legal document and gets a short, structured summary of it. |
| **Draft** | The user asks Legal Lens to draft a legal case document or a legal memo. The draft is based on the user's instructions and any documents they uploaded. |

---

## 4. Key User Flows

1. **Upload and ask:** the user uploads a document, then asks questions about its contents.
2. **Upload and summarize:** the user uploads a document and asks for a summary.
3. **Prompt and draft:** the user describes what they need (for example, "Draft a memo on…") and gets a draft back.
4. **Prompt bar / search bar:** a single main input where the user types questions or instructions, with a document upload option next to it.
5. **Mode selection:** the user can choose between **Ask**, **Summary** and **Draft**, or the app can work out the intent from the prompt.

> Ask and Summary need at least one uploaded document. Without one, the app asks the user to upload a document first.

---

## 5. Build Phases

> **v1 runs locally on one machine:** the frontend and backend both run on localhost, with no login and no user accounts.

### Phase 1: Frontend
- **Tech:** HTML, CSS and a JavaScript framework. There's no strong preference between **React** and **Angular**. *Suggestion: React + Vite, for a lightweight setup and a large ecosystem.*
- **Responsibilities:**
  - Take input from lawyers and clients.
  - Document upload.
  - Prompt / search bar for questions and instructions.
  - Show answers, summaries and drafts.
  - Switch between Ask, Summary and Draft.

### Phase 2: Backend
- **Tech:** Python + **FastAPI**
- **Package and dependency management:** **uv**
- **Responsibilities:**
  - REST APIs that the frontend calls.
  - Receive and process document uploads.
  - Route requests to the AI layer.
  - Return responses to the frontend.

### Phase 3: AI Layer
- **Approach (now):** a **RAG (Retrieval-Augmented Generation)** application.
- **Future:** could grow into a **multi-agent** system or another more advanced design.

---

## 6. Deliberately Deferred (Decide During Technical Architecture)

These details are left open on purpose for now:

- Vector database choice
- Embedding model
- Which local LLM (hosting is decided: local)
- RAG variant and strategy (chunking, retrieval, re-ranking, etc.)

---

## 7. Next Step

Write a **BRD (Business Requirements Document)** that covers:
- Functional specifications
- Non-functional specifications
- Other relevant details (scope, assumptions, constraints, success criteria)
- Open items, carried over from section 9

---

## 8. Suggestions to Consider

*Each item is open to accept, change or reject.*

### Trust and accuracy
- **Citations and source grounding:** each answer points back to the page or section of the source document it came from, so lawyers can check it quickly and made-up answers are easier to spot.
- **"Not legal advice" disclaimer:** state clearly that outputs are AI-generated and need review by a qualified attorney.
- **Evaluation set:** build a gold-standard set of legal questions and answers to measure answer quality over time.

### Security and confidentiality
- **Confidentiality and attorney-client privilege:** encrypt data in transit and at rest, define data retention and deletion policies, and never train models on client data.
- **Local deployment and data flow:** v1 runs on the lawyer's own machine, **including the AI models**. Documents never leave the machine, and the app works offline after setup.
- ~~**External LLM usage:** if a third-party model is used, choose providers or settings with zero data retention.~~ *Not applicable: v1 uses local models only.*
- ~~**Authentication and multi-tenancy:** keep each user's or each firm's documents separate.~~ *Deferred: not needed for a single-user local v1.*
- ~~**Audit log:** record who asked what and what was returned.~~ *Deferred: not needed for a single-user local v1. Chat history (below) covers the lawyer's own needs.*

### Documents
- **Supported file types:** PDF and DOCX at minimum. Scanned PDFs would need OCR. Support for these is still to be decided.
- **Multi-document Q&A:** ask across several documents at once, for example to compare two contracts.

### Drafting
- **Templates:** memo, brief, motion, letter, etc.
- **Editing and export:** edit drafts in the app and export them to DOCX or PDF.

### Experience
- **Chat history and sessions:** reopen past conversations and the documents used in them.
- **Jurisdiction awareness:** let the user set a jurisdiction (US federal or state, other countries) for more relevant answers.

### Non-functional
- Latency targets (for example, time to first response)
- Maximum document size and page limits
- Local performance: runs well on a typical lawyer's laptop (memory and CPU/GPU use)
- Easy local setup (ideally a single command to start)
- Accessibility (WCAG)
- *Not a concern for v1:* scalability, concurrent users, uptime targets

---

## 9. Open Questions

> **Status:** these questions are left open on purpose. They will be listed as open items in the BRD and answered before or during the technical architecture phase.

1. **Compliance:** are there requirements such as GDPR or ABA ethics rules on confidentiality and AI use?

### Answered
- ~~Primary user~~ → **Solo lawyer**
- ~~Scope of "Ask"~~ → **Uploaded documents only**
- ~~Users and login~~ → **Single user, on their own machine**
- ~~Practice area~~ → **General / mixed** (no single practice area)
- ~~Persistence~~ → **Documents and chat history are kept locally** until the user deletes them
- ~~File types~~ → **Text-based PDF and DOCX** (no OCR in v1)
- ~~v1 extras~~ → **Citations to source** are in. Multi-document Q&A, draft templates and export are out.
- ~~Draft output~~ → **Shown in the app with a Copy button** (no export in v1)
- ~~AI model hosting~~ → **Local models only** (specific models chosen in the technical architecture phase)
- ~~Production-grade bar~~ → **Tests + CI, one-command setup, logging + error handling, AI evaluation set**

> All of the above is captured in [LegalLens_BRD.md](LegalLens_BRD.md).
