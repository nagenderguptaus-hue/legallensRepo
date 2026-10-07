"""Loads the class demo data into a running backend, through the public API only (so it works
against any deployment: uv, Docker, another port). Synthetic content only, never client data.

Mirrors the frontend mock's story: a lease and an NDA that are Ready, a scan that Failed, and
conversations covering ask (with a follow-up), not found, summary, draft memo, clarify and a
deleted source document.

    uv run legallens-api                          # in one terminal
    uv run python scripts/seed_demo.py            # in another
    uv run python scripts/seed_demo.py --fresh    # wipe everything first (loopback only)
    uv run python scripts/seed_demo.py --url http://127.0.0.1:8010
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_documents import PDF, DemoFile, lease, nda, scanned

from tests.factories import make_pdf

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
Json = dict[str, Any]

# Uploaded, used in one conversation, then deleted: shows the "source deleted" notice (FR-21).
RETIRED = DemoFile(
    "Old_Engagement_Letter.pdf",
    make_pdf(
        [
            [
                "ENGAGEMENT LETTER",
                "This letter confirms that Lake & Hill LLP will represent Maple Street Bakery Inc. "
                "in its lease negotiation with Harbor Properties LLC.",
                "1. Fees",
                "Our hourly rate for this engagement is $350, billed monthly.",
            ]
        ]
    ),
    PDF,
)


def upload(client: httpx.Client, file: DemoFile) -> Json:
    res = client.post("/api/documents", files={"file": (file.name, file.content, file.mime)})
    if res.status_code == 409 and res.json()["code"] == "duplicate_document":
        existing: Json = next(
            d for d in client.get("/api/documents").json() if d["name"] == file.name
        )
        print(f"  {file.name}: already in the library")
        return existing
    res.raise_for_status()
    print(f"  {file.name}: uploaded")
    created: Json = res.json()
    return created


def wait_until_processed(client: httpx.Client, doc: Json, timeout_s: float = 120) -> Json:
    deadline = time.monotonic() + timeout_s
    while doc["status"] == "processing":
        if time.monotonic() > deadline:
            sys.exit(f"{doc['name']} is still processing after {timeout_s:.0f}s")
        time.sleep(0.5)
        doc = client.get(f"/api/documents/{doc['id']}").json()
    print(f"  {doc['name']}: {doc['status']}")
    return doc


def ask(client: httpx.Client, conversation_id: str, message: str, doc: Json | None) -> None:
    body = {
        "conversation_id": conversation_id,
        "message": message,
        "document_ids": [doc["id"]] if doc else [],
    }
    with client.stream("POST", "/api/chat/stream", json=body) as stream:
        stream.raise_for_status()
        for _ in stream.iter_bytes():
            pass


def conversation(client: httpx.Client, title: str, doc: Json | None, messages: list[str]) -> str:
    conv = client.post("/api/conversations", json={}).json()
    for message in messages:
        ask(client, conv["id"], message, doc)
    client.patch(f"/api/conversations/{conv['id']}", json={"title": title}).raise_for_status()
    print(f"  {title}")
    return str(conv["id"])


def wipe(client: httpx.Client, base: str) -> None:
    if urlparse(base).hostname not in LOOPBACK:
        sys.exit("--fresh deletes everything; it only runs against a loopback address.")
    for conv in client.get("/api/conversations").json():
        client.delete(f"/api/conversations/{conv['id']}").raise_for_status()
    for doc in client.get("/api/documents").json():
        client.delete(f"/api/documents/{doc['id']}").raise_for_status()
    print("Wiped all conversations and documents.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--fresh", action="store_true", help="delete all data first")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    with httpx.Client(base_url=base, timeout=120) as client:
        client.get("/api/health").raise_for_status()
        if args.fresh:
            wipe(client, base)

        print("Documents:")
        docs = [upload(client, f) for f in (scanned(), RETIRED, nda(), lease())]
        the_scan, retired, the_nda, the_lease = (wait_until_processed(client, d) for d in docs)
        del the_scan  # stays Failed on purpose: shows Retry / Delete

        if client.get("/api/conversations").json():
            print("Conversations already exist; skipped them (use --fresh to start over).")
            return

        # Oldest first, so the newest lands at the top of the sidebar.
        print("Conversations:")
        conversation(
            client,
            "Engagement letter: fees",
            retired,
            ["What is the hourly rate for this engagement?"],
        )
        client.delete(f"/api/documents/{retired['id']}").raise_for_status()
        conversation(client, "NDA: what can I help with?", the_nda, ["nda"])
        conversation(client, "NDA summary", the_nda, ["Summarize this NDA"])
        conversation(
            client, "Memo: tenant exit options", the_lease, ["Draft a memo on my exit options"]
        )
        conversation(
            client,
            "Lease: early termination rights",
            the_lease,
            [
                "Can the tenant terminate the lease early?",
                "How much written notice does that require?",
                "Does the lease include a non-compete clause?",
            ],
        )
    print("Done. Open the app and pick a conversation from the sidebar.")


if __name__ == "__main__":
    main()
