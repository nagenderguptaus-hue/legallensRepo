"""CLI commands for indexing, retrieval and the three workflows (registered by ``cli.py``).

legallens-ai index [--pages] contract.pdf         ingest a .pdf / .docx (OCR for scanned
                                                  pages) or a page-fixture .json
legallens-ai docs                                 list indexed documents
legallens-ai forget doc_msa                       delete a document's chunks and vectors
legallens-ai search --doc doc_msa "late fees"     retrieval only (local, free): the chunk table
legallens-ai ask --doc doc_msa "question"         one question; omit it for a chat that keeps
                                                  history, so follow-ups exercise the rewriter
legallens-ai summarize --doc doc_msa              six-section summary
legallens-ai draft [--doc doc_msa] "instructions" a draft; omit the text to chat and revise
legallens-ai eval-rewrite                         score the query rewriter
legallens-ai eval-ask                             score the Ask workflow (BRD §6 targets)
legallens-ai bench-retrieval                      embedding / reranker bake-off (LegalBench-RAG)
legallens-ai bench-ocr --configs ...              OCR engine / settings bake-off (synthetic scans)
"""

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

from legallens_ai.config import AISettings
from legallens_ai.errors import OrchestratorError
from legallens_ai.events import CitationEvent, DoneEvent, StatusEvent, TokenEvent, WorkflowEvent
from legallens_ai.ingestion import PageReport, make_ingestor
from legallens_ai.query_rewriter import QueryRewriter
from legallens_ai.retrieval import Retrieval, open_retrieval
from legallens_ai.retrieval.loaders import document_id_for, load_document
from legallens_ai.retrieval.types import RetrievalResult
from legallens_ai.schemas import DocumentInfo, Intent, OrchestratorRequest, Turn
from legallens_ai.workflow_evals import (
    ASK_CASES,
    REWRITE_CASES,
    ask_report,
    ask_results_json,
    index_eval_documents,
    load_ask_cases,
    load_rewrite_cases,
    rewrite_report,
    run_ask_cases,
    run_rewrite_cases,
)
from legallens_ai.workflows import (
    AskTrace,
    AskWorkflow,
    DraftTrace,
    DraftWorkflow,
    SummaryTrace,
    SummaryWorkflow,
)
from legallens_ai.workflows.generation import GenerationTrace

DIM = "\033[2m" if sys.stdout.isatty() else ""
RESET = "\033[0m" if sys.stdout.isatty() else ""


def _say(text: str = "") -> None:
    print(f"{DIM}{text}{RESET}")


async def _document(retrieval: Retrieval, document_id: str) -> DocumentInfo:
    indexed = await retrieval.store.document(document_id)
    if indexed is None:
        known = ", ".join(d.id for d in await retrieval.store.documents()) or "none"
        raise SystemExit(f"Unknown document {document_id!r}. Indexed: {known}")
    return DocumentInfo(id=indexed.id, name=indexed.name, type=indexed.type, pages=indexed.pages)


async def _render(events: AsyncIterator[WorkflowEvent]) -> str:
    """Prints a workflow's stream as it arrives; returns the answer text."""
    text: list[str] = []
    citations: list[CitationEvent] = []
    at_line_start = True
    async for event in events:
        if isinstance(event, StatusEvent):
            if not at_line_start:
                print()
            _say(f"… {event.label}")
            at_line_start = True
        elif isinstance(event, TokenEvent):
            print(event.text, end="", flush=True)
            text.append(event.text)
            at_line_start = event.text.endswith("\n")
        elif isinstance(event, CitationEvent):
            citations.append(event)
        elif isinstance(event, DoneEvent):
            print()
            for c in citations:
                quote = " ".join(c.quote.split())
                quote = quote if len(quote) <= 160 else quote[:157] + "..."
                _say(f"  [{c.index}] p. {c.page} · {c.section or '-'}: {quote}")
            _say(f"outcome: {event.outcome}")
    return "".join(text)


def _retrieval_table(result: RetrievalResult) -> None:
    _say(
        f"retrieval: vector {result.vector_hits} + BM25 {result.keyword_hits} → "
        f"{result.candidates} candidates → top {len(result.chunks)} "
        f"(search {result.timings_ms.get('search_ms', 0):.0f} ms, "
        f"rerank {result.timings_ms.get('rerank_ms', 0):.0f} ms)"
    )
    _say("   score  vec  bm25  page  section")
    for sc in result.chunks:
        _say(
            f"  {sc.rerank_score:6.2f}  {sc.vector_rank or '-':>3}  {sc.keyword_rank or '-':>4}"
            f"  {sc.chunk.page:>4}  {(sc.chunk.section or '-')[:50]}"
        )


def _generation_line(g: GenerationTrace | None) -> None:
    if g is None:
        return
    first = f"{g.first_token_ms:.0f} ms" if g.first_token_ms is not None else "-"
    cached = f", {g.cache_read_tokens:,} cached" if g.cache_read_tokens else ""
    _say(
        f"model: {g.model or g.requested_model} | first text {first} | total "
        f"{g.latency_ms:.0f} ms | {g.usage.input_tokens:,} in{cached} / "
        f"{g.usage.output_tokens:,} out tokens | stop: {g.stop_reason}"
    )


# ---------------------------------------------------------------- index / docs / search


async def _index(args: argparse.Namespace, settings: AISettings) -> int:
    retrieval = await open_retrieval(settings)
    ingestor = make_ingestor(settings, retrieval)
    try:
        for path in args.files:
            doc_id = args.id if args.id and len(args.files) == 1 else None
            suffix = path.suffix.lower()
            if suffix == ".json":
                loaded = load_document(path, doc_id)
                doc = await retrieval.indexer.index(
                    document_id=loaded.id, name=loaded.name, type=loaded.type, pages=loaded.pages
                )
            elif suffix in {".pdf", ".docx"}:
                started = time.perf_counter()
                outcome = await ingestor.ingest(
                    document_id=doc_id or document_id_for(path),
                    name=path.name,
                    type="pdf" if suffix == ".pdf" else "docx",
                    path=path,
                )
                doc = outcome.document
                if args.pages:
                    _page_reports(outcome.reports)
                ocr = sum(r.route == "ocr" for r in outcome.reports)
                _say(
                    f"{ocr} of {len(outcome.reports)} pages OCR'd, "
                    f"{time.perf_counter() - started:.1f} s"
                )
                for warning in outcome.warnings:
                    print(f"warning: {warning}")
            else:
                print(f"{path}: unsupported file type (use .pdf, .docx or a .json fixture)")
                continue
            print(
                f"{doc.id}: {doc.name}, {doc.pages} pages, {doc.chunks} chunks, {doc.words:,} words"
            )
    finally:
        await retrieval.close()
    return 0


def _page_reports(reports: list[PageReport]) -> None:
    print(f"{'page':>4}  {'route':<7} {'paras':>5} {'words':>6} {'ocr conf':>8} {'ms':>7}")
    for r in reports:
        conf = f"{r.ocr_confidence:.3f}" if r.ocr_confidence is not None else "-"
        print(f"{r.page:>4}  {r.route:<7} {r.paragraphs:>5} {r.words:>6} {conf:>8} {r.ms:>7.0f}")


async def _docs(args: argparse.Namespace, settings: AISettings) -> int:
    retrieval = await open_retrieval(settings)
    try:
        documents = await retrieval.store.documents()
    finally:
        await retrieval.close()
    if not documents:
        print("No documents indexed. Try: legallens-ai index evals/documents/msa.json")
    for d in documents:
        print(
            f"{d.id:<24} {d.name:<36} {d.pages:>4} pages {d.chunks:>5} chunks "
            f"~{d.estimated_tokens:>7,} tokens  {d.indexed_at}"
        )
    return 0


async def _forget(args: argparse.Namespace, settings: AISettings) -> int:
    retrieval = await open_retrieval(settings)
    try:
        await retrieval.indexer.purge(args.document_id)
    finally:
        await retrieval.close()
    print(f"Deleted {args.document_id} (chunks and vectors).")
    return 0


async def _search(args: argparse.Namespace, settings: AISettings) -> int:
    retrieval = await open_retrieval(settings)
    try:
        doc = await _document(retrieval, args.doc)
        result = await retrieval.retriever.retrieve(
            document_id=doc.id, document_name=doc.name, query=" ".join(args.query)
        )
        _retrieval_table(result)
        if args.show_text:
            for sc in result.chunks:
                print(f"\n--- p. {sc.chunk.page} · {sc.chunk.section} ({sc.rerank_score:.2f})")
                print(sc.chunk.text)
    finally:
        await retrieval.close()
    return 0


# ---------------------------------------------------------------- workflows


async def _chat_loop(
    first: str | None, one: Callable[[str, list[Turn]], Awaitable[tuple[str, Intent]]]
) -> int:
    """One message, or an interactive session that keeps history for follow-ups."""
    history: list[Turn] = []
    if first:
        await one(first, history)
        return 0
    print("Type a message and press Enter (empty line or Ctrl+C to quit).")
    while True:
        try:
            line = (await asyncio.to_thread(input, "\n> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            return 0
        try:
            answer, intent = await one(line, history)
        except OrchestratorError as exc:
            print(f"error: {exc.code}: {exc.message}")
            continue
        history += [Turn("user", line), Turn("assistant", answer, intent)]


async def _ask(args: argparse.Namespace, settings: AISettings) -> int:
    retrieval = await open_retrieval(settings)
    try:
        doc = await _document(retrieval, args.doc)
        workflow = AskWorkflow.from_settings(
            settings, store=retrieval.store, retriever=retrieval.retriever
        )

        async def one(message: str, history: list[Turn]) -> tuple[str, Intent]:
            trace = AskTrace()
            request = OrchestratorRequest(message=message, history=history, document=doc)
            answer = await _render(workflow.run(request, trace))
            if trace.rewrite:
                r = trace.rewrite
                detail = f" → {r.query}" if r.rewritten else ""
                _say(f"rewrite: {r.reason}{detail}")
            if trace.retrieval and args.show_chunks:
                _retrieval_table(trace.retrieval)
            elif trace.retrieval and trace.retrieval.best_score is not None:
                _say(f"best rerank score: {trace.retrieval.best_score:.2f}")
            if trace.gated:
                _say(f"stopped by the reranker gate (threshold {workflow.min_score})")
            _generation_line(trace.generation)
            if trace.warnings:
                _say(f"warnings: {', '.join(trace.warnings)}")
            return answer, "ask"

        return await _chat_loop(" ".join(args.question) or None, one)
    finally:
        await retrieval.close()


async def _summarize(args: argparse.Namespace, settings: AISettings) -> int:
    retrieval = await open_retrieval(settings)
    try:
        doc = await _document(retrieval, args.doc)
        workflow = SummaryWorkflow.from_settings(settings, store=retrieval.store)
        trace = SummaryTrace()
        message = " ".join(args.message) or "Summarize this document."
        await _render(workflow.run(OrchestratorRequest(message=message, document=doc), trace))
        _say(f"model chosen: {trace.model} (document ~{trace.estimated_tokens:,} tokens)")
        _generation_line(trace.generation)
        sections = ", ".join(
            f"{s.heading}: {'ok' if s.ok else 'MISSING' if not s.present else 'uncited'}"
            for s in trace.sections
        )
        _say(f"sections: {sections}")
        if trace.warnings:
            _say(f"warnings: {', '.join(trace.warnings)}")
    finally:
        await retrieval.close()
    return 0


async def _draft(args: argparse.Namespace, settings: AISettings) -> int:
    retrieval = await open_retrieval(settings)
    try:
        doc = await _document(retrieval, args.doc) if args.doc else None
        workflow = DraftWorkflow.from_settings(settings, store=retrieval.store)

        async def one(message: str, history: list[Turn]) -> tuple[str, Intent]:
            trace = DraftTrace()
            request = OrchestratorRequest(message=message, history=history, document=doc)
            answer = await _render(workflow.run(request, trace))
            _generation_line(trace.generation)
            if trace.check:
                _say(f"placeholders: {trace.check.placeholders}")
                if trace.check.invented_citations:
                    _say(f"INVENTED CITATIONS: {list(trace.check.invented_citations)}")
            return answer, "draft"

        return await _chat_loop(" ".join(args.instructions) or None, one)
    finally:
        await retrieval.close()


# ---------------------------------------------------------------- evals


async def _eval_rewrite(args: argparse.Namespace, settings: AISettings) -> int:
    cases = load_rewrite_cases(args.cases)
    if args.only:
        cases = [c for c in cases if c.id.startswith(tuple(args.only))]
    rewriter = QueryRewriter.from_settings(settings)
    print(f"Running {len(cases)} rewrite cases against {rewriter.model_name} ...\n")
    results = await run_rewrite_cases(rewriter, cases, concurrency=args.concurrency)
    print(rewrite_report(results))
    return 0 if all(r.correct for r in results) else 1


async def _eval_ask(args: argparse.Namespace, settings: AISettings) -> int:
    cases = load_ask_cases(args.cases)
    if args.only:
        cases = [c for c in cases if c.id.startswith(tuple(args.only))]
    # The eval indexes its documents into a separate folder; models are shared.
    eval_settings = settings.model_copy(update={"data_dir": settings.data_dir / "eval"})
    retrieval = await open_retrieval(eval_settings)
    try:
        documents = await index_eval_documents(retrieval, {c.document for c in cases})
        workflow = AskWorkflow.from_settings(
            eval_settings, store=retrieval.store, retriever=retrieval.retriever
        )
        print(
            f"Running {len(cases)} Ask cases ({workflow.model_name}, top "
            f"{retrieval.retriever.top_n}, gate {workflow.min_score}) ...\n"
        )
        results = await run_ask_cases(workflow, cases, documents, concurrency=args.concurrency)
    finally:
        await retrieval.close()
    print(ask_report(results))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(ask_results_json(results), encoding="utf-8")
        print(f"\nPer-case results written to {args.out}")
    return 0 if all(r.correct for r in results) else 1


async def _bench_retrieval(args: argparse.Namespace, settings: AISettings) -> int:
    from legallens_ai import retrieval_bench as bench
    from legallens_ai.retrieval.models import make_embedder, make_reranker

    if not (bench.LBR_DIR / "benchmarks").exists():
        raise SystemExit(f"LegalBench-RAG not found in {bench.LBR_DIR}. See retrieval_bench.py.")
    embedders = [make_embedder(m, settings.models_dir) for m in args.embedders]
    rerankers = [make_reranker(m, settings.models_dir) for m in args.rerankers]
    report, raw = await bench.bake_off(
        embedders, rerankers, rerank_on=args.rerank_on, seed=args.seed, k=args.k
    )
    print()
    print(report)
    bench.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = bench.RESULTS_DIR / f"bench-seed{args.seed}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"\nResults written to {out}")
    return 0


async def _bench_ocr(args: argparse.Namespace, settings: AISettings) -> int:
    from legallens_ai import ocr_bench

    unknown = set(args.configs) - set(ocr_bench.CONFIGS)
    if unknown:
        raise SystemExit(
            f"Unknown configs {sorted(unknown)}; choose from {list(ocr_bench.CONFIGS)}"
        )
    await ocr_bench.run_bench(
        args.configs,
        args.qualities,
        settings=settings,
        retrieval=args.retrieval,
        limit=args.limit,
    )
    return 0


Command = Callable[[argparse.Namespace, AISettings], Coroutine[Any, Any, int]]
COMMANDS: dict[str, Command] = {
    "index": _index,
    "docs": _docs,
    "forget": _forget,
    "search": _search,
    "ask": _ask,
    "summarize": _summarize,
    "draft": _draft,
    "eval-rewrite": _eval_rewrite,
    "eval-ask": _eval_ask,
    "bench-retrieval": _bench_retrieval,
    "bench-ocr": _bench_ocr,
}


def add_parsers(sub: Any) -> None:
    p = sub.add_parser(
        "index", help="ingest .pdf / .docx (loader or OCR per page) or page-fixture .json files"
    )
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--id", help="document id (default: from the file name or fixture)")
    p.add_argument("--pages", action="store_true", help="print how each page was read")

    sub.add_parser("docs", help="list indexed documents")

    p = sub.add_parser("forget", help="delete a document's chunks and vectors")
    p.add_argument("document_id")

    p = sub.add_parser("search", help="hybrid retrieval only (local, no API calls)")
    p.add_argument("--doc", required=True, help="document id (see `docs`)")
    p.add_argument("query", nargs="+")
    p.add_argument("--show-text", action="store_true", help="print each chunk's text")

    p = sub.add_parser("ask", help="Ask workflow; omit the question for a chat with history")
    p.add_argument("--doc", required=True, help="document id (see `docs`)")
    p.add_argument("question", nargs="*")
    p.add_argument("--show-chunks", action="store_true", help="print the retrieval table")

    p = sub.add_parser("summarize", help="Summary workflow")
    p.add_argument("--doc", required=True, help="document id (see `docs`)")
    p.add_argument("message", nargs="*", help='optional, e.g. "focus on the risks"')

    p = sub.add_parser("draft", help="Draft workflow; omit the instructions to chat and revise")
    p.add_argument("--doc", help="optional reference document id")
    p.add_argument("instructions", nargs="*")

    p = sub.add_parser("eval-rewrite", help="score the query rewriter")
    p.add_argument("--cases", type=Path, default=REWRITE_CASES)
    p.add_argument("--only", nargs="+", help="run only case ids with these prefixes")
    p.add_argument("--concurrency", type=int, default=4)

    p = sub.add_parser("eval-ask", help="score the Ask workflow")
    p.add_argument("--cases", type=Path, default=ASK_CASES)
    p.add_argument("--only", nargs="+", help="run only case ids with these prefixes")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--out", type=Path, help="write per-case results as JSON")

    p = sub.add_parser("bench-retrieval", help="embedding / reranker bake-off (local, no API)")
    p.add_argument("--embedders", nargs="+", default=["BAAI/bge-base-en-v1.5"])
    p.add_argument("--rerankers", nargs="*", default=[])
    p.add_argument("--rerank-on", help='embedder whose candidates the rerankers score, or "best"')
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("-k", type=int, default=25, help="top-k from vector and from BM25")

    p = sub.add_parser("bench-ocr", help="OCR engine / settings bake-off (local, no API)")
    p.add_argument("--configs", nargs="+", default=["rapid-small", "tesseract-300dpi"])
    p.add_argument("--qualities", nargs="+", default=["clean", "noisy", "fax"])
    p.add_argument("--retrieval", action="store_true", help="also check retrieval on OCR'd text")
    p.add_argument("--limit", type=int, help="only the first N pages (quick runs)")
