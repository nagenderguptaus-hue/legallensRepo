# Legal Lens — Frontend TODO (UI only, mock data)

> **Status:** ✅ implemented (Oct 5, 2026). Lint, typecheck, 40 unit/component tests and the e2e demo path all pass. Differences from the plan are marked **Note:**.
> **Scope:** UI layer only. No backend, orchestration or AI.
> **Traces to:** [LegalLens_BRD.md](../LegalLens_BRD.md) v1.1 (FR/NFR ids) and [architecture/legal_lens_flow.excalidraw](../architecture/legal_lens_flow.excalidraw)

---

## 1. Approach in one paragraph

We build the real React app against the **real API contract** from the architecture diagram (`/api/conversations`, `/api/documents`, `POST /api/chat/stream` over SSE). We serve it from **mock data** using **MSW (Mock Service Worker)**, which intercepts network requests in the browser. The UI code calls actual endpoints and never imports mock data directly. When the FastAPI backend exists, we switch MSW off and nothing in the UI changes. The mock layer also simulates token streaming, intent detection, citations, document ingestion progress (including OCR) and errors. That way every state the real system can be in can be designed, demoed and tested now.

---

## 2. Design direction

**Inspiration (adapted, not copied):**
- **Claude:** a calm, warm, light canvas, and assistant messages without bubbles.
- **ChatGPT:** sidebar structure, conversations grouped by date, a composer centred in the empty state.
- **Perplexity:** inline numbered citations, with a "Sources" list under each answer.
- **Harvey / legal tools:** serif type for legal documents, and a serious, trustworthy tone.

**Visual language:** professional, light, quiet. Trust comes from restraint: no gradients, no dark theme, no playful colours.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#FAF9F6` warm paper | app canvas |
| `--surface` | `#FFFFFF` | cards, panels, composer |
| `--sidebar` | `#F4F2ED` | sidebar background |
| `--border` | `#E6E3DC` | dividers, card borders |
| `--text` / `--text-muted` | `#1D2433` / `#5B6475` | body / secondary text (both pass WCAG AA) |
| `--primary` | `#1F3A5F` deep navy (hover `#183050`, soft `#E8EEF6`) | primary actions, focus ring, citation chips |
| `--intent-ask / -summary / -draft` | blue `#1D4ED8` / teal `#0F766E` / violet `#6D28D9` | intent badges |
| `--warning` (`#B45309` on `#FEF3C7`) | amber | `[CITATION NEEDED]` placeholders, OCR warnings |
| `--success` / `--danger` | `#15803D` / `#B91C1C` | Ready status / Failed status, destructive actions |

**Type:**
- **Inter** for the UI.
- **Source Serif 4** for drafts, summaries and the wordmark, to give a legal-document feel.
- Both are **self-hosted via `@fontsource`**, so no CDN is used and the app works offline (NFR-4).

**Shape & motion:** 8 px spacing grid · corner radius 10 px for controls and 14 px for cards · soft shadows · 150–200 ms ease-out transitions · all motion turned off under `prefers-reduced-motion`.

### Layout (desktop ≥ 1280 px)
```
┌──────────────┬──────────────────────────────────────────┬────────────────────┐
│ ⚖ Legal Lens │  NDA review ✎        [📄 Mutual_NDA.docx] │ Documents   Source │
│ [+ New chat] │──────────────────────────────────────────│────────────────────│
│ 🔍 Search     │                                          │ ┌ Drop files ─────┐│
│              │   You: What is the term of the NDA?      │ └─────────────────┘│
│ Today        │                                          │ ● Lease.pdf  Ready │
│  NDA review  │   [ASK] The agreement lasts 3 years [1]  │ ◐ Opinion.pdf  OCR │
│  Lease Q&A   │   from the Effective Date [2] …          │   page 7 / 12 ▓▓░  │
│ Yesterday    │   Sources: [1] NDA p.2 §4  [2] p.1 §1    │ ✕ Scan.pdf  Failed │
│  Memo draft  │                                          │   [Retry] [Delete] │
│ …            │  ┌────────────────────────────────────┐  │                    │
│──────────────│  │ 📎 Ask, summarize or draft …     ➤ │  │                    │
│ ● Local model│  └────────────────────────────────────┘  │                    │
│ 🔒 Offline   │  AI-generated · not legal advice         │                    │
└──────────────┴──────────────────────────────────────────┴────────────────────┘
  Sidebar 280px          Chat (max 760px text column)         Panel 380px (toggle)
```

---

## 3. Tech stack (frontend)

| Concern | Choice | Why |
|---|---|---|
| Framework | **React 19 + Vite + TypeScript (strict)** | Matches the BRD, fast dev server, typed contracts |
| Styling | **Plain CSS: design tokens + CSS Modules** | Fits the "HTML + CSS" brief, readable for students, no utility-class clutter |
| Accessible primitives | **Radix UI** (Dialog, DropdownMenu, Tooltip, Tabs, Toast) | Correct focus trapping, keyboard support and ARIA without hand-rolling it; unstyled, so it fits our tokens |
| Icons | **lucide-react** | Consistent, light line icons |
| Routing | **React Router** (`/`, `/c/:conversationId`) | Deep links to conversations, browser back/forward works |
| Server state | **TanStack Query** | Caching, refetch and polling for ingestion status, optimistic rename/delete |
| UI state | **Zustand** (small store) | Sidebar collapsed, panel open, active document, streaming state |
| Markdown | **react-markdown + remark-gfm** | Answers and drafts with lists, tables and headings |
| Mocking | **MSW 2** (REST + streamed SSE) | Mocks the real API at the network level, so it can be switched off later |
| Tests | **Vitest + React Testing Library** (+ MSW in tests), **Playwright** smoke test | Unit and component tests now, plus one end-to-end demo-path test |
| Quality | ESLint + Prettier + `tsc --noEmit` | Matches the BRD's CI requirements |

---

## 4. Folder skeleton (to be created after approval)

```
LegalLens/frontend/
├── index.html · package.json · vite.config.ts · tsconfig.json · README.md
├── public/mockServiceWorker.js          # generated by MSW
└── src/
    ├── main.tsx                         # starts MSW in dev, then renders <App/>
    ├── app/        App.tsx · router.tsx · providers.tsx · AppShell.tsx
    ├── styles/     tokens.css · globals.css · fonts.css
    ├── api/        types.ts · client.ts · conversations.ts · documents.ts · chatStream.ts (SSE parser)
    ├── mocks/      browser.ts · db.ts (in-memory + localStorage)
    │               handlers/ conversations.ts · documents.ts · chat.ts · health.ts
    │               engine/   intent.ts · responses.ts · stream.ts · ingestion.ts
    │               data/     documents.ts · conversations.ts · pages.ts
    ├── components/ui/   Button · IconButton · Badge · Tooltip · Dialog · Menu · Toast · Skeleton · Kbd · Spinner
    ├── features/
    │   ├── sidebar/     Sidebar · ConversationList · ConversationItem · SearchBox · SidebarFooter
    │   ├── chat/        ChatView · EmptyState · MessageList · UserMessage · AssistantMessage
    │   │                IntentBadge · CitationChip · SourcesList · StreamingIndicator · ClarifyChips · NotFoundNotice
    │   │   └── renderers/  AnswerView · SummaryView · DraftView
    │   ├── composer/    Composer · DocumentContextPicker · AttachButton
    │   ├── documents/   DocumentsPanel · UploadDropzone · DocumentCard · IngestionProgress · GlobalDropOverlay
    │   ├── source/      SourceViewer · PagePreview · HighlightedExcerpt
    │   └── system/      ModelStatus · OfflineBadge · ErrorBanner · ShortcutsDialog
    ├── hooks/      useChatStream · useAutoScroll · useHotkeys · useDocuments · useConversations
    ├── store/      uiStore.ts
    ├── lib/        dates.ts (Today / Yesterday / Previous 7 days) · format.ts · cn.ts
    └── test/       setup.ts · e2e/demo.spec.ts
```

---

## 5. TODO — phased

### Phase 0 · Prerequisites
- [x] Install **Node.js LTS** (`winget install OpenJS.NodeJS.LTS`), then confirm: Node v24.19.0 · npm 11.17.0
- [x] Get your approval of this TODO

### Phase 1 · Scaffold
- [x] Create the Vite React-TS project in `LegalLens/frontend/` and install dependencies (§3)
- [x] Set up strict TypeScript, ESLint, Prettier, and the `@/` path alias
- [x] Add npm scripts: `dev`, `build`, `preview`, `lint`, `typecheck`, `test`, `test:e2e`
- [x] Write a README covering how to run it, how mocks work, and how to switch to the real backend (`VITE_USE_MOCKS=false`)

### Phase 2 · Design system
- [x] `tokens.css`: colours, spacing, radius, shadows, z-index, motion (§2)
- [x] Self-hosted Inter + Source Serif 4, and global styles (focus ring, scrollbars, selection colour)
- [x] UI primitives: Button (primary / secondary / ghost / danger, sizes, loading), IconButton (with required `aria-label`), Badge, Tooltip, Dialog (with a confirm variant), Menu, Toast, Skeleton, Kbd, Spinner

### Phase 3 · API contract + mock backend (MSW)
- [x] `api/types.ts`: `Conversation`, `Message`, `Citation`, `Document`, `IngestionStage`, `Intent`, and the SSE event union (`intent | token | citation | done | error`)
- [x] API client: JSON fetch wrapper that understands the error envelope `{ code, message, request_id }`
- [x] `chatStream.ts`: reads SSE over `fetch` + `ReadableStream`, because `EventSource` can't send POST requests. Supports **abort** (Stop button).
- [x] Mock database: seeded data stored in memory and **saved to localStorage**, so chats survive a reload (FR-19 feel), with a "Reset demo data" action
- [x] **Note (contract additions for the backend):** `intent` events carry the new message ids, a new `status` event reports progress, `done` carries `outcome` / `suggestions` / `title`, and there is a new `POST /api/documents/{id}/retry`. All are documented in `src/api/types.ts` and the README.
- [x] Mock intent engine: keyword rules → `summary` ("summar…"), `draft` ("draft / memo / brief"), `clarify` (very short or ambiguous), otherwise `ask`
- [x] Mock response engine: canned responses per document and intent, with realistic citations and a **not-found** case
- [x] Mock streaming: intent event → tokens every ~15–30 ms → citations → done. Simulated latency.
- [x] Mock ingestion state machine: Validating → Reading pages / **OCR page n/N** → Quality check → Indexing → Ready / Failed (with warnings), polled through `GET /api/documents/{id}`
- [x] Dev controls (dev builds only): force slow stream, force errors, model runtime offline

### Phase 4 · App shell & routing
- [x] Three-column `AppShell`: sidebar, chat and documents panel, each collapsible
- [x] Routes: `/` (new chat, empty state) and `/c/:id` (conversation). Unknown id → a friendly "Conversation not found" page.
- [x] Skip link, page `<title>` set to the conversation title, and remembered sidebar/panel state

### Phase 5 · Sidebar (FR-19, FR-20)
- [x] Wordmark, collapse toggle, **New chat** button (shortcut `Ctrl+Shift+O`)
- [x] Conversation search (`Ctrl+K`), filtered instantly as you type, with a "No matches" state
- [x] List grouped **Today / Yesterday / Previous 7 days / Older**, active item highlighted, long titles truncated with a tooltip
- [x] Hover/focus menu: **Rename** (inline edit; Enter saves, Esc cancels, optimistic) · **Delete** (confirm dialog, toast with result)
- [x] Loading skeletons, empty state ("No conversations yet")
- [x] Footer: **local model status** (green Ready / amber Loading / red Unavailable, from `/api/health`) and a 🔒 *"Offline · data stays on this device"* badge (NFR-4)

### Phase 6 · Chat thread (FR-6 – FR-18, FR-22, FR-23)
- [x] **Empty state:** greeting, a one-line privacy promise, 3 example prompts (Ask / Summarize / Draft) that fill the composer, and a hint to upload a document if the library is empty
- [x] User message: right-aligned soft bubble, with copy-on-hover
- [x] Assistant message: full width, no bubble; **intent badge** (Ask / Summary / Draft) appears as soon as the `intent` event arrives
- [x] Streaming: blinking caret, a **Stop generating** button, and auto-scroll that **pauses when the user scrolls up**, with a "↓ Jump to latest" pill
- [x] **Ask view:** markdown answer with inline **citation chips** `[1]`
  - Hover a chip to see a tooltip with the document, page, section and quote
  - Click a chip to open the Source Viewer
  - A **Sources** list sits under the answer
- [x] **Not-found view:** a calm info notice, *"I couldn't find this in the document"*, with tips for rephrasing (FR-9)
- [x] **Summary view:** structured card with the 6 fixed sections; each section shows its citations, or a muted "Not found in document" (FR-12, FR-13)
- [x] **Draft view:** a "paper" card in serif type with a memo header (To / From / Date / Re)
  - `[CITATION NEEDED]` and `[CONFIRM: …]` show as **amber highlights** with an explanatory tooltip (FR-17)
  - Copy button with a "Copied" confirmation (FR-18)
- [x] **Clarify view:** the assistant's question plus quick-reply chips ("Summarize it", "Answer a question", "Draft a memo")
- [x] Message actions: Copy · Retry (on error) · timestamps on hover
- [x] Persistent disclaimer under the composer: *"AI-generated content. Not legal advice. Review before use."* (FR-23)

### Phase 7 · Composer
- [x] Auto-growing textarea (max 8 lines). **Enter** sends, **Shift+Enter** adds a new line, and Enter is ignored while an IME is composing text.
- [x] Send button disabled when the input is empty or a reply is streaming. While streaming, it becomes **Stop**.
- [x] **Document context picker** chip: shows the active document and lets the user switch to another Ready document (one document in v1, per FR-6). Processing and Failed documents appear but can't be selected.
- [x] 📎 Attach opens the file picker and uploads through the documents API, with progress shown in the panel
- [x] Character counter shown near the limit · draft text kept per conversation when switching chats

### Phase 8 · Documents panel & upload (FR-1 – FR-5, FR-21)
- [x] Panel with **Library | Source** tabs, toggled from the top bar (`Ctrl+.`)
- [x] **Dropzone** plus a drop overlay that covers the whole app when dragging files in
- [x] Client-side checks before upload: type (PDF / DOCX), ≤ 25 MB, not empty. Clear inline errors (NFR-3).
- [x] **Document card:** file icon, name, pages, size, uploaded date; status pill (Processing / Ready / Failed)
  - **Live ingestion progress**, stage by stage, including *"OCR · page 7 of 12"*
  - **Warnings** shown in a disclosure (e.g. "Low OCR confidence on pages 3, 9")
- [x] Failed documents get **Retry** and **Delete** actions. Delete opens a confirm dialog that explains *file, extracted text and index entries will be removed* (FR-5).
- [x] "Use in chat" sets the active document for the composer
- [x] Conversations whose source document was deleted show a "source document deleted" notice (FR-21)

### Phase 9 · Source viewer (citations → evidence)
- [x] Opens on citation click: document name, page n of N, previous/next page
- [x] Mock **page preview** (paper-styled text page) with the **cited excerpt highlighted** and scrolled into view
- [x] Badge marking OCR pages ("Text recognised by OCR, may contain errors")
- [x] "Back to library", and the previously focused citation chip gets focus back when the viewer closes

### Phase 10 · System states & feedback
- [x] Toasts for: upload complete, document deleted, conversation renamed or deleted, copy, errors (with `request_id`)
- [x] Banner when the **model runtime is unavailable** (mock toggle), with Retry; sending is disabled with an explanation
- [x] Stream error mid-answer: partial text kept, an inline error, and **Retry**
- [x] 404 page for conversations, and an app-level error boundary with a "Reload" action
- [x] Keyboard shortcuts dialog (`?`)

### Phase 11 · Accessibility & responsive (NFR-9)
- [x] Full keyboard path: sidebar → thread → composer → panel. Visible focus ring everywhere.
- [x] `aria-live="polite"` announces when a reply **is complete**, not every token. Intent and status are announced as text, never by colour alone.
- [x] Colour contrast checked at WCAG 2.1 AA; `prefers-reduced-motion` respected. **Note:** the colour pairs were chosen to meet AA, but no automated accessibility audit (e.g. axe) has been run yet.
- [x] Breakpoints:
  - ≥ 1280 px: three columns
  - 1024–1279 px: the panel overlays the chat
  - 768–1023 px: the sidebar collapses to icons
  - < 768 px: the sidebar becomes a drawer and the panel a bottom sheet
  - **Note:** as built, the sidebar becomes a drawer below 1024 px. On desktop it collapses to an icon rail on demand (`Ctrl+B`). On phones the panel is a full-width slide-over rather than a bottom sheet.

### Phase 12 · Tests & quality
- [x] Unit tests: SSE parser (including chunk boundaries), date grouping, intent mock, upload validation
- [x] Component tests (RTL + MSW):
  - sending a message streams and renders citations
  - rename and delete a conversation
  - upload → Processing → Ready
  - Stop generating
  - not-found answer
- [x] Playwright smoke test of the BRD §7 demo path (runs on the installed Microsoft Edge, so no browser download is needed): upload → ask with citations → unanswerable question → summary → draft with placeholders → reload → reopen conversation → delete document
- [x] `lint`, `typecheck`, `test` and `build` all pass with zero warnings

### Phase 13 · Polish & demo readiness
- [x] Favicon and wordmark (⚖ + "Legal Lens" in serif), tidy page titles
- [x] Review spacing, alignment and empty / loading / error states on every screen
- [x] Seeded demo data that tells a story (below), plus a "Reset demo data" action
- [x] Screenshots for the README and the class slides

---

## 6. Mock data (seed)

| Documents | State | Shows |
|---|---|---|
| `Commercial_Lease_Agreement.pdf` (24 pp, digital) | Ready | Ask with citations, Summary |
| `Mutual_NDA.docx` (6 pp) | Ready | Ask, Draft memo with placeholders |
| `Smith_v_Jones_Opinion.pdf` (12 pp, **scanned**) | Ready with OCR warnings | Source Viewer OCR badge, case brief draft |
| `Vendor_MSA_scan.pdf` | Processing (OCR in progress) | Live progress |
| `Corrupted_file.pdf` | Failed | Retry and Delete |

**Conversations:** about 7 across Today, Yesterday, Previous 7 days and Older. They cover:
- an Ask thread with follow-ups (shows the query editor in action),
- a not-found answer,
- a full Summary,
- a Draft memo,
- a case brief,
- a clarify exchange,
- a conversation whose source document was deleted.

---

## 7. Out of scope (this phase)
Real backend calls, authentication, dark theme, draft editing or export, multi-document Q&A, internationalisation.

## 8. Definition of done
- `npm run dev` opens a fully clickable app backed by mocks.
- Every flow in BRD §7 can be demoed with no backend.
- Every component has its loading, empty and error states.
- Keyboard-only use works throughout.
- `lint`, `typecheck`, `test` and `build` are green.
- Switching `VITE_USE_MOCKS=false` makes the UI call the real `/api/*` endpoints, with no code changes.
