"""Command line for trying the orchestrator by hand.

legallens-ai classify "Summarize this lease"          one message
legallens-ai classify --no-document "What is ...?"    as if no document were selected
legallens-ai classify                                 interactive: one message per line
legallens-ai classify --show-prompt "..."             also print the user turn sent to the model
legallens-ai eval                                     run evals/intent_cases.jsonl, print scores
legallens-ai chat [--doc <id>]                        full chat turns, as the backend runs them

Indexing, retrieval and the Ask / Summary / Draft workflows: see ``cli_workflows.py``
(`legallens-ai --help` lists every command).
"""

import argparse
import asyncio
import io
import logging
import sys
from pathlib import Path

from legallens_ai import cli_chat, cli_workflows
from legallens_ai.config import AISettings
from legallens_ai.errors import OrchestratorError
from legallens_ai.evaluation import DEFAULT_CASES, load_cases, report, run_cases, to_json
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.orchestrator import Orchestrator
from legallens_ai.schemas import DocumentInfo, OrchestratorRequest

DEMO_DOCUMENT = DocumentInfo(id="doc_demo", name="Commercial_Lease.pdf", type="pdf", pages=12)


async def _classify(args: argparse.Namespace) -> int:
    classifier = IntentClassifier.from_settings(AISettings())
    orchestrator = Orchestrator(classifier)
    document = None if args.no_document else DEMO_DOCUMENT

    async def one(message: str) -> None:
        if args.show_prompt:
            print("--- user turn sent to the model ---")
            print(classifier.render(message))
            print("-----------------------------------")
        try:
            d = await orchestrator.route(OrchestratorRequest(message=message, document=document))
        except OrchestratorError as exc:
            print(f"error: {exc.code}: {exc.message}")
            return
        print(f"intent:         {d.intent}")
        print(f"needs_document: {d.needs_document}")
        print(f"rationale:      {d.rationale}")
        print(
            f"model:          {d.model} | {d.latency_ms:.0f} ms | "
            f"{d.usage.input_tokens} in / {d.usage.output_tokens} out tokens"
        )

    if args.message:
        await one(" ".join(args.message))
        return 0
    print("Type a message and press Enter (empty line or Ctrl+C to quit).")
    while True:
        try:
            line = (await asyncio.to_thread(input, "> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            return 0
        await one(line)
        print()


async def _eval(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    if args.only:
        cases = [c for c in cases if c.id.startswith(tuple(args.only))]
    classifier = IntentClassifier.from_settings(AISettings())
    print(f"Running {len(cases)} cases against {classifier.model_name} ...\n")
    results = await run_cases(classifier, cases, concurrency=args.concurrency)
    print(report(results))
    if args.out:
        args.out.write_text(to_json(results), encoding="utf-8")
        print(f"\nPer-case results written to {args.out}")
    return 0 if all(r.correct for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="legallens-ai",
        description=f"{__doc__}\n{cli_workflows.__doc__}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show log lines")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("classify", help="classify one message, or interactively")
    c.add_argument("message", nargs="*", help="the message (omit for interactive mode)")
    c.add_argument("--no-document", action="store_true", help="pretend no document is selected")
    c.add_argument("--show-prompt", action="store_true", help="print the user turn sent")

    e = sub.add_parser("eval", help="score the classifier on the labelled cases")
    e.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="JSONL file of cases")
    e.add_argument("--only", nargs="+", help="run only case ids with these prefixes")
    e.add_argument("--concurrency", type=int, default=4)
    e.add_argument("--out", type=Path, help="write per-case results as JSON")

    cli_workflows.add_parsers(sub)
    cli_chat.add_parser(sub)

    args = parser.parse_args(argv)
    # Model rationales can contain non-ASCII; never crash on a legacy Windows code page.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    try:
        if args.command == "chat":
            return asyncio.run(cli_chat.chat(args, AISettings()))
        if args.command in cli_workflows.COMMANDS:
            return asyncio.run(cli_workflows.COMMANDS[args.command](args, AISettings()))
        return asyncio.run(_classify(args) if args.command == "classify" else _eval(args))
    except OrchestratorError as exc:  # e.g. missing API key, raised before any call
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
