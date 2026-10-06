"""Loads demo data into a running backend: a synthetic NDA (PDF) and a short lease (DOCX),
plus one conversation with an answered question. Synthetic content only, never client data.

    uv run legallens-api                 # in one terminal
    uv run python scripts/seed_demo.py   # in another  (--url to target another host/port)
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.factories import make_docx, make_pdf  # dev-only script: reuses the test documents

LEASE_PAGES = [
    [
        "COMMERCIAL LEASE AGREEMENT",
        "This Lease is made on January 15, 2026 between Harbor Properties LLC (Landlord) and "
        "Maple Street Bakery Inc. (Tenant).",
        "1. Premises",
        "Landlord leases to Tenant the ground-floor unit at 12 Harbor Way.",
    ],
    [
        "2. Rent",
        "Tenant shall pay monthly rent of $4,500 on the first day of each month.",
        "3. Term",
        "The term of this Lease is five (5) years from the Commencement Date.",
    ],
    [
        "4. Default",
        "If Tenant fails to pay rent within ten (10) days after it is due, Landlord may "
        "terminate this Lease.",
        "5. Indemnification",
        "Tenant shall indemnify Landlord against claims arising from Tenant's use of the Premises.",
    ],
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    base = parser.parse_args().url.rstrip("/")

    with httpx.Client(base_url=base, timeout=60) as client:
        client.get("/api/health").raise_for_status()
        ids = []
        for name, content, mime in [
            ("Mutual_NDA.pdf", make_pdf(), "application/pdf"),
            (
                "Commercial_Lease.docx",
                make_docx(LEASE_PAGES),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ]:
            res = client.post("/api/documents", files={"file": (name, content, mime)})
            if res.status_code == 409:
                print(f"skip {name}: {res.json()['message']}")
                continue
            res.raise_for_status()
            ids.append(res.json()["id"])
            print(f"uploaded {name} -> {ids[-1]}")

        for doc_id in ids:
            for _ in range(60):
                status = client.get(f"/api/documents/{doc_id}").json()["status"]
                if status != "processing":
                    print(f"{doc_id}: {status}")
                    break
                time.sleep(0.5)

        if ids:
            conversation = client.post("/api/conversations", json={}).json()
            body = {
                "conversation_id": conversation["id"],
                "message": "How long does the agreement remain in effect?",
                "document_ids": [ids[0]],
            }
            with client.stream("POST", "/api/chat/stream", json=body) as stream:
                for _ in stream.iter_bytes():
                    pass
            print(f"conversation {conversation['id']} created with one answered question")


if __name__ == "__main__":
    main()
