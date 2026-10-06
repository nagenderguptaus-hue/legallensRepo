"""Generate the Legal Lens architecture flow as an Excalidraw file + an SVG preview.

Usage (standard library only, no dependencies):
    python generate_flow_diagram.py [out.excalidraw] [out.svg]

Defaults write legal_lens_flow.excalidraw and legal_lens_flow.svg next to this script.
Edit the coordinates / text below and re-run to regenerate both files.
"""
import json
import random
import sys
from html import escape
from pathlib import Path

random.seed(42)  # stable element ids/seeds so regenerated files diff cleanly
HERE = Path(__file__).parent
OUT_EXCALIDRAW = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "legal_lens_flow.excalidraw"
OUT_SVG = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "legal_lens_flow.svg"

els = []      # excalidraw elements
warnings = []
_id = 0


def uid():
    global _id
    _id += 1
    return f"el{_id:04d}"


def seed():
    return random.randint(1, 2**31 - 1)


def base(t, x, y, w, h, stroke="#1e1e1e", fill="transparent", sw=2, style="solid",
         groups=None, roundness=None):
    return dict(id=uid(), type=t, x=x, y=y, width=w, height=h, angle=0,
                strokeColor=stroke, backgroundColor=fill, fillStyle="solid",
                strokeWidth=sw, strokeStyle=style, roughness=0, opacity=100,
                groupIds=groups or [], frameId=None, roundness=roundness,
                seed=seed(), version=1, versionNonce=seed(), isDeleted=False,
                boundElements=[], updated=1, link=None, locked=False)


def est_w(text, size, mono=False):
    f = 0.6 if mono else 0.55
    return max(len(line) for line in text.split("\n")) * size * f


def est_h(text, size):
    return len(text.split("\n")) * size * 1.25


def text(x, y, s, size=16, color="#1e1e1e", mono=False, align="left", groups=None):
    w, h = est_w(s, size, mono), est_h(s, size)
    e = base("text", x, y, w, h, stroke=color, groups=groups)
    e.update(text=s, originalText=s, fontSize=size, fontFamily=3 if mono else 2,
             textAlign=align, verticalAlign="top", containerId=None,
             autoResize=True, lineHeight=1.25)
    els.append(e)
    return e


KINDS = {
    "fe": ("#ffffff", "#1971c2"),
    "be": ("#ffffff", "#2f9e44"),
    "orch": ("#ffffff", "#e8590c"),
    "ai": ("#ffffff", "#6741d9"),
    "llm": ("#fff3bf", "#f08c00"),
    "retr": ("#e5dbff", "#7048e8"),
    "check": ("#ffffff", "#e03131"),
    "store": ("#f8f9fa", "#495057"),
    "sqlite": ("#d3f9d8", "#2f9e44"),
}


def box(x, y, w, h, title, body=None, kind="fe", tsize=18, bsize=15, mono=False,
        center=False):
    fill, stroke = KINDS[kind]
    g = uid()
    r = base("rectangle", x, y, w, h, stroke=stroke, fill=fill, groups=[g],
             roundness={"type": 3})
    els.append(r)
    pad = 14
    inner_w = w - 2 * pad
    total_h = est_h(title, tsize) + (6 + est_h(body, bsize) if body else 0)
    if total_h > h - 2 * pad + 4:
        warnings.append(f"HEIGHT overflow in '{title}': {total_h:.0f} > {h - 2 * pad}")
    for s, sz, mo in ((title, tsize, False), (body, bsize, mono)):
        if s and est_w(s, sz, mo) > inner_w:
            warnings.append(f"WIDTH overflow in '{title}': {est_w(s, sz, mo):.0f} > {inner_w}")
    if center:
        ty = y + (h - total_h) / 2
        text(x + (w - est_w(title, tsize)) / 2, ty, title, tsize, align="center", groups=[g])
        if body:
            text(x + (w - est_w(body, bsize, mono)) / 2, ty + est_h(title, tsize) + 6, body,
                 bsize, "#343a40", mono, align="center", groups=[g])
    else:
        text(x + pad, y + pad, title, tsize, groups=[g])
        if body:
            text(x + pad, y + pad + est_h(title, tsize) + 6, body, bsize, "#343a40", mono,
                 groups=[g])
    return r


def diamond(x, y, w, h, title, body, fill, stroke, tsize=18, bsize=15):
    g = uid()
    els.append(base("diamond", x, y, w, h, stroke=stroke, fill=fill, groups=[g]))
    total_h = est_h(title, tsize) + 6 + est_h(body, bsize)
    for s, sz in ((title, tsize), (body, bsize)):
        if est_w(s, sz) > w * 0.55:
            warnings.append(f"WIDTH overflow in diamond '{title}'")
    ty = y + (h - total_h) / 2
    text(x + (w - est_w(title, tsize)) / 2, ty, title, tsize, align="center", groups=[g])
    text(x + (w - est_w(body, bsize)) / 2, ty + est_h(title, tsize) + 6, body, bsize,
         "#343a40", align="center", groups=[g])


def container(x, y, w, h, title, stroke, fill="#ffffff", style="solid", tsize=20):
    els.append(base("rectangle", x, y, w, h, stroke=stroke, fill=fill, sw=2, style=style,
                    roundness={"type": 3}))
    if title:
        text(x + 16, y + 10, title, tsize, stroke)


def lane(y, h, title, fill, stroke):
    els.append(base("rectangle", 0, y, 3800, h, stroke=stroke, fill=fill, sw=2,
                    roundness={"type": 3}))
    text(24, y + 16, title, 26, stroke)


def arrow(pts, data=False, both=False, color=None):
    x0, y0 = pts[0]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    color = color or ("#868e96" if data else "#343a40")
    e = base("arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys), stroke=color,
             sw=2, style="dashed" if data else "solid")
    e.update(points=[[px - x0, py - y0] for px, py in pts], lastCommittedPoint=None,
             startBinding=None, endBinding=None,
             startArrowhead="arrow" if both else None, endArrowhead="arrow", elbowed=False)
    els.append(e)


def label(x, y, s, size=14, color="#495057"):
    text(x, y, s, size, color)


# ---------------------------------------------------------------- title + legend
text(0, -215, "Legal Lens — Technical Architecture: End-to-End Flow", 40)
text(0, -150, "v1  ·  runs fully local  ·  React  →  FastAPI  →  LangChain orchestration  →  "
              "advanced RAG  ·  SQLite conversation DB", 20, "#495057")

container(2440, -215, 1360, 165, "Legend", "#495057", tsize=18)
els.append(base("rectangle", 2470, -168, 44, 26, stroke="#f08c00", fill="#fff3bf",
                roundness={"type": 3}))
label(2526, -165, "calls the local LLM", 16, "#1e1e1e")
els.append(base("rectangle", 2770, -168, 44, 26, stroke="#7048e8", fill="#e5dbff",
                roundness={"type": 3}))
label(2826, -165, "retrieval step", 16, "#1e1e1e")
els.append(base("rectangle", 3040, -168, 44, 26, stroke="#e03131", fill="#ffffff",
                roundness={"type": 3}))
label(3096, -165, "guard / check", 16, "#1e1e1e")
els.append(base("diamond", 3300, -172, 40, 34, stroke="#e03131", fill="#ffe3e3"))
label(3352, -165, "decision", 16, "#1e1e1e")
arrow([(2470, -100), (2530, -100)])
label(2545, -110, "request / control flow", 16, "#1e1e1e")
arrow([(2770, -100), (2830, -100)], data=True)
label(2845, -110, "data read / write", 16, "#1e1e1e")
arrow([(3040, -100), (3100, -100)], both=True)
label(3115, -110, "request ⇄ response", 16, "#1e1e1e")

# ---------------------------------------------------------------- lanes
lane(0, 480, "1   FRONTEND  —  React + Vite + TypeScript  ·  http://localhost:5173",
     "#e7f5ff", "#1971c2")
lane(560, 640, "2   BACKEND  —  FastAPI (Python 3.12, uv)  ·  http://127.0.0.1:8000",
     "#ebfbee", "#2f9e44")
lane(1280, 480, "3   ORCHESTRATION  —  LangChain (LCEL chains · RunnableBranch by intent)",
     "#fff4e6", "#e8590c")
lane(1840, 1460, "4   AI LAYER  —  ingestion pipeline & advanced RAG workflows "
                 "(all models run locally)", "#f3f0ff", "#6741d9")
lane(3380, 480, "5   DATA & MODELS  —  everything stays on the lawyer's machine",
     "#f1f3f5", "#495057")

# ---------------------------------------------------------------- 1 frontend
container(40, 70, 700, 380, "Sidebar", "#1971c2")
box(70, 120, 640, 50, "+  New Chat", kind="fe", center=True)
box(70, 190, 640, 240, "Past Conversations",
    "search box\n•  Lease review — Oct 1\n•  NDA questions — Sep 30\n•  Memo draft — Sep 29\n"
    "click to open  ·  rename  ·  delete", kind="fe")

container(780, 70, 2000, 380, "Chat Workspace", "#1971c2")
box(810, 120, 1940, 200, "Message Thread",
    "answers stream in token by token  ·  intent badge:  Ask / Summary / Draft\n"
    "citation chips  [p.4 §2.1]  open the cited passage in the Source Viewer\n"
    "drafts get a Copy button  ·  disclaimer: AI-generated content, not legal advice",
    kind="fe", bsize=16)
box(810, 340, 1940, 90, "Prompt Bar",
    "[ attach file ]        Ask, summarize or draft from your documents …        [ Send ]",
    kind="fe", bsize=16)

container(2820, 70, 940, 380, "Documents Panel", "#1971c2")
box(2850, 120, 880, 80, "Upload", "drag & drop PDF / DOCX  (digital or scanned)", kind="fe")
box(2850, 215, 880, 110, "Library",
    "name · pages · status:  Processing → Ready / Failed\nlayout / OCR warnings  ·  delete",
    kind="fe")
box(2850, 340, 880, 90, "Source Viewer", "page preview + highlighted cited excerpt", kind="fe")
arrow([(2750, 220), (2800, 220), (2800, 385), (2850, 385)])  # citation chip -> viewer

# ---------------------------------------------------------------- 2 backend
box(40, 630, 700, 320, "Conversations API",
    "GET    /api/conversations       list\n"
    "POST   /api/conversations       new chat\n"
    "GET    /api/conversations/{id}  open\n"
    "PATCH  /api/conversations/{id}  rename\n"
    "DELETE /api/conversations/{id}  delete\n\n"
    "open → messages + citations",
    kind="be", mono=True)
box(780, 630, 980, 320, "Chat API  —  Server-Sent Events (SSE)",
    "POST /api/chat/stream\n"
    "{ conversation_id, message, document_ids[] }\n"
    "← text/event-stream\n"
    "  event: intent    {ask|summary|draft|clarify}\n"
    "  event: token     {text}\n"
    "  event: citation  {source, doc_id, page, section, quote}\n"
    "  event: done      {message_id}\n"
    "  event: error     {code, message, request_id}",
    kind="be", mono=True)
box(1800, 630, 980, 320, "Middleware & System",
    "CORS: localhost only  ·  Request-ID on every call\n"
    "Pydantic request / response validation\n"
    "error envelope  { code, message, request_id }\n"
    "structured JSON logs + per-step timings\n"
    "upload limits:  ≤ 25 MB  ·  ≤ 300 pages  ·  PDF / DOCX\n"
    "GET /api/health  →  SQLite · model runtime · indexes",
    kind="be", bsize=16)
box(2820, 630, 940, 320, "Documents API",
    "POST   /api/documents                upload\n"
    "GET    /api/documents                library\n"
    "GET    /api/documents/{id}           status\n"
    "GET    /api/documents/{id}/pages/{n} preview\n"
    "DELETE /api/documents/{id}           delete\n\n"
    "delete → file + chunks + vectors",
    kind="be", mono=True)
box(40, 1000, 3720, 150, "Service Layer",
    "ConversationService     ·     ChatService  (calls orchestration, relays SSE)     ·     "
    "DocumentService  (validate, save file, enqueue ingestion)\n"
    "TransactionLogger  —  every user action (upload, ask, rename, delete …) is written to "
    "the transactions table with its request_id and latency",
    kind="be", bsize=16)

# frontend <-> backend
arrow([(390, 430), (390, 630)], both=True)
label(402, 505, "REST / JSON")
arrow([(1270, 430), (1270, 630)], both=True)
label(1282, 505, "POST  +  SSE stream")
arrow([(3290, 450), (3290, 630)], both=True)
label(3302, 505, "REST / multipart upload")
# routers -> service layer
for x in (390, 1270, 3290):
    arrow([(x, 950), (x, 1000)])

# ---------------------------------------------------------------- 3 orchestration
box(40, 1360, 540, 260, "1  Load Context",
    "•  last N turns of this conversation\n•  rolling summary of older turns\n"
    "•  selected document_ids\n•  read from SQLite", kind="orch")
box(640, 1360, 500, 260, "2  Input Guard",
    "•  length limits\n•  empty-library check\n•  prompt-injection screening\n"
    "•  document text = data, never\n    instructions", kind="check")
diamond(1220, 1320, 660, 340, "3  Intent Router (LLM)",
        "structured output →\nask | summary | draft | clarify", "#fff3bf", "#f08c00")
box(1980, 1360, 760, 260, "5  Response Composer",
    "•  merges answer + verified citations\n"
    "•  emits SSE events: intent · token · citation · done\n"
    "•  'clarify' → asks the user a follow-up question\n"
    "•  persists the turn via ChatService → SQLite", kind="orch")
box(2820, 1360, 940, 260, "Ingestion Job Runner",
    "•  background queue, 1 worker\n•  enqueue(doc_id) → run pipeline → retry ≤ 2\n"
    "•  status: Processing → Ready / Failed\n•  job state kept in ingestion_jobs table",
    kind="orch")

arrow([(310, 1150), (310, 1360)])
label(322, 1215, "ChatService.stream()")
arrow([(580, 1490), (640, 1490)])
arrow([(1140, 1490), (1220, 1490)])
arrow([(1880, 1490), (1980, 1490)])
label(1893, 1462, "clarify", 13)
arrow([(2360, 1360), (2360, 1150)])
label(2372, 1215, "SSE events")
arrow([(3290, 1150), (3290, 1360)])
label(3302, 1215, "enqueue(doc_id)")

# persistence bus on the far left: service layer + load context <-> SQLite
arrow([(40, 1075), (-50, 1075), (-50, 3615), (40, 3615)], data=True)
arrow([(40, 3615), (-50, 3615), (-50, 1560), (40, 1560)], data=True)
label(-330, 2350, "read / write:\nconversations\nmessages\ncitations\ntransactions", 15)

# ---------------------------------------------------------------- 4 AI layer: RAG
container(30, 1900, 2760, 1370, "RAG Workflows  —  one LangChain chain per intent", "#6741d9",
          fill="#fbfaff")
# override title position so the router trunk (x=70) does not cross it
els[-1]["x"] = 110

C = [100 + 330 * i for i in range(8)]  # 8 columns, 290 wide
ROW_S, ROW_A, ROW_R, ROW_D = 1995, 2235, 2510, 2795
for row_y, name in ((ROW_S, "SUMMARY workflow"), (ROW_A, "ASK workflow"),
                    (ROW_D, "DRAFT workflow")):
    label(100, row_y - 26, name, 16, "#e8590c")

# summary row (4 wide boxes)
box(100, ROW_S, 620, 140, "S1  Load document",
    "all chunks in reading order, grouped by section\n(SQLite chunks table)", kind="ai")
box(760, ROW_S, 620, 140, "S2  Map  —  summarize each section",
    "local LLM  ·  keeps page / section refs per point", kind="llm")
box(1420, ROW_S, 620, 140, "S3  Reduce  —  fixed template",
    "type & purpose · parties · key dates · obligations\nnotable risks · plain-language overview",
    kind="llm")
box(2080, ROW_S, 620, 140, "S4  Coverage & citation check",
    "every part cited, or marked\n'Not found in document'", kind="check")
for i in range(3):
    arrow([(720 + 660 * i, ROW_S + 70), (760 + 660 * i, ROW_S + 70)])

# ask row
box(C[0], ROW_A, 290, 170, "A1  Query Editor",
    "rewrites the follow-up into\na standalone query using\nchat history + 3 variants",
    kind="llm")
box(C[5], ROW_A, 290, 170, "A2  Sufficiency gate",
    "best re-rank score ≥ τ ?\nno → 'I couldn't find this\nin the document'", kind="check")
box(C[6], ROW_A, 290, 170, "A3  Grounded answer",
    "context-only prompt\ninline cites [S1] … [S6]\nstreams tokens", kind="llm")
box(C[7], ROW_A, 290, 170, "A4  Citation verifier",
    "each [Sx] ∈ retrieved set\nquote matches source\nflags unsupported claims",
    kind="check")
arrow([(C[5] + 290, ROW_A + 85), (C[6], ROW_A + 85)])
arrow([(C[6] + 290, ROW_A + 85), (C[7], ROW_A + 85)])

# shared retrieval
container(410, ROW_R - 50, 1320, 260, "Advanced Retrieval  —  shared by Ask & Draft", "#7048e8",
          fill="#f3f0ff", style="dashed", tsize=16)
box(C[1], ROW_R, 290, 190, "R1  Hybrid search",
    "dense: vector top-20\nsparse: BM25 top-20\nfilter: document_ids\nboth run in parallel",
    kind="retr")
box(C[2], ROW_R, 290, 190, "R2  Fusion",
    "Reciprocal Rank\nFusion (RRF)\n→ top-20 candidates", kind="retr")
box(C[3], ROW_R, 290, 190, "R3  Re-rank",
    "local cross-encoder\nscores query ↔ chunk\n→ top-6", kind="retr")
box(C[4], ROW_R, 290, 190, "R4  Context builder",
    "parent-chunk expansion\ndedupe · token budget\ntags [S1 … S6] with\npage + section",
    kind="retr")
for i in (1, 2, 3):
    arrow([(C[i] + 290, ROW_R + 95), (C[i + 1], ROW_R + 95)])

# draft row
box(C[0], ROW_D, 290, 170, "D1  Parse request",
    "type: memo / case brief /\nfree-form  ·  key facts\n+ reference document", kind="llm")
box(C[5], ROW_D, 290, 170, "D2  Outline",
    "template skeleton for\nthe chosen draft type", kind="ai")
box(C[6], ROW_D, 290, 170, "D3  Section drafting",
    "facts only from context\n+ user instructions\nstreams tokens", kind="llm")
box(C[7], ROW_D, 290, 170, "D4  Placeholder guard",
    "unknown fact → [CONFIRM: …]\nno source → [CITATION\nNEEDED], never invented",
    kind="check")
arrow([(C[5] + 290, ROW_D + 85), (C[6], ROW_D + 85)])
arrow([(C[6] + 290, ROW_D + 85), (C[7], ROW_D + 85)])

# router trunk -> each workflow
for row_mid, name in ((ROW_S + 70, "summary"), (ROW_A + 85, "ask"), (ROW_D + 85, "draft")):
    arrow([(1550, 1660), (1550, 1800), (14, 1800), (14, row_mid), (100, row_mid)],
          color="#f08c00")
label(1562, 1690, "4  route by intent", 15, "#e8590c")

# ask / draft <-> retrieval
arrow([(200, ROW_A + 170), (200, ROW_R + 60), (C[1], ROW_R + 60)])
label(212, ROW_A + 200, "query +\n3 variants", 13)
arrow([(300, ROW_D), (300, ROW_R + 140), (C[1], ROW_R + 140)])
label(312, ROW_D - 70, "fact query", 13)
arrow([(1620, ROW_R), (1620, ROW_A + 85), (C[5], ROW_A + 85)])
label(1630, ROW_A + 190, "context\n[S1 … S6]", 13)
arrow([(1620, ROW_R + 190), (1620, ROW_D + 85), (C[5], ROW_D + 85)])
label(1630, ROW_R + 215, "context", 13)

# workflow results -> response composer (return trunk on the right)
for row_mid in (ROW_S + 70, ROW_A + 85, ROW_D + 85):
    arrow([(2700, row_mid), (2730, row_mid), (2730, 1790), (2360, 1790), (2360, 1620)])
label(2372, 1680, "result + citations", 15)

# ---------------------------------------------------------------- 4 AI layer: ingestion
container(2820, 1900, 940, 1370, "Ingestion Pipeline  (background)", "#6741d9", fill="#fbfaff")
box(2850, 1955, 880, 95, "1  Validate",
    "magic-byte type check · ≤ 25 MB · ≤ 300 pages · not encrypted · SHA-256 dedupe",
    kind="check")
diamond(3065, 2085, 450, 180, "2  Page check", "text layer on page?", "#ffe3e3", "#e03131")
box(2850, 2300, 420, 170, "3a  Digital page",
    "layout parser:\nheadings · paragraphs\nlists · tables", kind="ai")
box(3310, 2300, 420, 170, "3b  Scanned page",
    "render → deskew → OCR\n+ layout detection\n(tables, columns)", kind="ai")
box(2850, 2510, 880, 110, "4  Layout & quality check",
    "reading order · OCR confidence · empty / garbled pages → warnings", kind="check")
box(2850, 2660, 880, 100, "5  Clean & normalize",
    "strip headers / footers / page numbers · fix hyphenation · page & section map",
    kind="ai")
box(2850, 2800, 880, 130, "6  Structure-aware chunking",
    "split on section boundaries · ~500 tokens · 15% overlap\n"
    "parent–child chunks · metadata {doc_id, page, section, heading path}", kind="ai")
box(2850, 2970, 880, 130, "7  Embed & index  (dual)",
    "child chunks → embedding model → Vector Store\n"
    "chunk text → BM25 index (SQLite FTS5)  ·  rows → SQLite", kind="ai")
box(2850, 3140, 880, 95, "8  Mark Ready / Failed",
    "status + warnings saved  ·  UI polls GET /api/documents/{id}", kind="ai")

arrow([(3290, 1620), (3290, 1955)])
label(3302, 1780, "run(doc_id)")
arrow([(3290, 2050), (3290, 2085)])
arrow([(3065, 2175), (2990, 2175), (2990, 2300)])
label(2870, 2140, "has text", 13)
arrow([(3515, 2175), (3600, 2175), (3600, 2300)])
label(3540, 2140, "image only", 13)
arrow([(3060, 2470), (3060, 2510)])
arrow([(3520, 2470), (3520, 2510)])
for y0, y1 in ((2620, 2660), (2760, 2800), (2930, 2970), (3100, 3140)):
    arrow([(3290, y0), (3290, y1)])

# ---------------------------------------------------------------- 5 data & models
box(40, 3450, 1000, 330, "SQLite  —  legallens.db   (conversation DB + transactions)",
    "conversations   id · title · created_at · updated_at\n"
    "messages        id · conversation_id · role · content · intent\n"
    "citations       id · message_id · chunk_id · page · quote\n"
    "documents       id · name · pages · sha256 · status · warnings\n"
    "chunks          id · document_id · parent_id · page · section\n"
    "chunks_fts      FTS5 virtual table → BM25 keyword index\n"
    "transactions    id · request_id · action · status · latency_ms\n"
    "ingestion_jobs  id · document_id · state · attempts · error",
    kind="sqlite", bsize=14, mono=True)
box(1080, 3450, 620, 330, "Vector Store  (local, embedded)",
    "child-chunk embeddings\n+ metadata {doc_id, page, section}\nfiltered similarity search\n\n"
    "product choice: decided in the\ntechnical architecture phase", kind="store")
box(1740, 3450, 1040, 330, "Local Model Runtime  (e.g. Ollama)",
    "Chat LLM — one model, several prompts:\n"
    "    intent router · query editor · answer · summary · draft\n"
    "Embedding model — ingestion + queries\n"
    "Cross-encoder re-ranker  (in-process)\n"
    "OCR + layout models  (in-process)\n"
    "bound to 127.0.0.1  ·  no outbound network calls", kind="store", bsize=16)
box(2820, 3450, 940, 330, "Local File Store",
    "./data/uploads/{doc_id}/original.pdf | .docx\n"
    "./data/pages/{doc_id}/page-{n}.png\n\n"
    "OCR input + Source Viewer page previews", kind="store", mono=True, bsize=15)

# retrieval reads
arrow([(575, ROW_R + 190), (575, 3450)], data=True)
label(587, 3080, "BM25 (FTS5)", 13)
arrow([(680, ROW_R + 190), (680, 3000), (1390, 3000), (1390, 3450)], data=True)
label(760, 2975, "vector search", 13)
# ingestion writes
arrow([(2850, 3035), (2805, 3035), (2805, 3340), (1550, 3340), (1550, 3450)], data=True)
label(1900, 3316, "embeddings", 13)
arrow([(3730, 3187), (3785, 3187), (3785, 3815), (900, 3815), (900, 3780)], data=True)
label(1900, 3822, "chunks · FTS5 · status", 13)
arrow([(3290, 3270), (3290, 3450)], data=True)
label(3302, 3300, "originals + page images", 13)

# ---------------------------------------------------------------- write excalidraw
doc = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
       "elements": els,
       "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
       "files": {}}
OUT_EXCALIDRAW.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")

# ---------------------------------------------------------------- write svg preview
minx, miny, maxx, maxy = -360, -240, 3840, 3900
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {miny} {maxx - minx} '
       f'{maxy - miny}" width="{maxx - minx}" height="{maxy - miny}">',
       '<defs><marker id="ah" markerWidth="10" markerHeight="10" refX="9" refY="5" '
       'orient="auto-start-reverse" markerUnits="userSpaceOnUse">'
       '<path d="M0,0 L10,5 L0,10" fill="none" stroke="context-stroke" '
       'stroke-width="2"/></marker></defs>',
       f'<rect x="{minx}" y="{miny}" width="{maxx - minx}" height="{maxy - miny}" '
       'fill="#ffffff"/>']
for e in els:
    st = e["strokeColor"]
    fill = "none" if e["backgroundColor"] == "transparent" else e["backgroundColor"]
    dash = ' stroke-dasharray="8 6"' if e["strokeStyle"] == "dashed" else ""
    if e["type"] == "rectangle":
        svg.append(f'<rect x="{e["x"]}" y="{e["y"]}" width="{e["width"]}" '
                   f'height="{e["height"]}" rx="10" fill="{fill}" stroke="{st}" '
                   f'stroke-width="{e["strokeWidth"]}"{dash}/>')
    elif e["type"] == "diamond":
        x, y, w, h = e["x"], e["y"], e["width"], e["height"]
        svg.append(f'<polygon points="{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} '
                   f'{x},{y + h / 2}" fill="{fill}" stroke="{st}" stroke-width="2"/>')
    elif e["type"] == "arrow":
        pts = " ".join(f'{e["x"] + px},{e["y"] + py}' for px, py in e["points"])
        start = ' marker-start="url(#ah)"' if e["startArrowhead"] else ""
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{st}" stroke-width="2"'
                   f'{dash}{start} marker-end="url(#ah)"/>')
    elif e["type"] == "text":
        fam = "Consolas, monospace" if e["fontFamily"] == 3 else "Helvetica, Arial, sans-serif"
        lines = e["text"].split("\n")
        anchor, tx = "start", e["x"]
        if e["textAlign"] == "center":
            anchor, tx = "middle", e["x"] + e["width"] / 2
        for i, line in enumerate(lines):
            ty = e["y"] + e["fontSize"] * (1.25 * i + 1)
            svg.append(f'<text x="{tx}" y="{ty}" font-family="{fam}" '
                       f'font-size="{e["fontSize"]}" fill="{st}" text-anchor="{anchor}" '
                       f'xml:space="preserve">{escape(line)}</text>')
svg.append("</svg>")
OUT_SVG.write_text("\n".join(svg), encoding="utf-8")

print(f"elements: {len(els)}")
print("\n".join(warnings) if warnings else "no overflow warnings")
