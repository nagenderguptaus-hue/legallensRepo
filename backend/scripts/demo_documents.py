"""Synthetic demo documents, built in code (never client data, no binaries in git).

Shared by ``seed_demo.py`` (uploads them through the API) and ``make_fixtures.py`` (writes them
to disk for the frontend's end-to-end tests). The lease is written so the class demo questions
work with the stand-in: "Can the tenant terminate the lease early?" finds §5, while "Does the
lease include a non-compete clause?" finds nothing.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.factories import NDA_PAGES, make_blank_pdf, make_docx, make_pdf  # dev-only reuse

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

LEASE_PAGES: list[list[str]] = [
    [
        "COMMERCIAL LEASE AGREEMENT",
        "This Commercial Lease Agreement is made on January 15, 2026 between Harbor Properties "
        "LLC, a Delaware limited liability company (Landlord), and Maple Street Bakery Inc., a "
        "California corporation (Tenant).",
        "1. Premises",
        "Landlord leases to Tenant the ground-floor retail unit at 12 Harbor Way, Oakland, "
        "California, comprising approximately 2,400 rentable square feet.",
        "2. Term",
        "The term of this Lease is five (5) years, beginning on March 1, 2026 (the Commencement "
        "Date) and ending on February 28, 2031, unless terminated earlier under this Lease.",
    ],
    [
        "3. Rent",
        "Tenant shall pay monthly Base Rent of $4,500 in advance on the first day of each month.",
        "Base Rent increases by three percent (3%) on each anniversary of the Commencement Date.",
        "A late charge of five percent (5%) of the overdue amount applies to any payment received "
        "more than five (5) days after its due date.",
        "4. Security Deposit",
        "Tenant shall deposit $9,000 with Landlord as security for its obligations. Landlord "
        "shall return the deposit within thirty (30) days after the Lease ends, less any amounts "
        "applied to unpaid rent or damage beyond normal wear and tear.",
    ],
    [
        "5. Early Termination",
        "Tenant may terminate this Lease early, effective at the end of the thirty-sixth (36th) "
        "month of the Term, by giving Landlord at least six (6) months' prior written notice and "
        "paying an early termination fee equal to three (3) months' Base Rent.",
        "6. Use",
        "Tenant shall use the Premises only as a retail bakery and cafe, and for no other "
        "purpose without Landlord's prior written consent.",
        "7. Maintenance and Repairs",
        "Landlord shall maintain the roof, foundation and structural walls. Tenant shall keep "
        "the interior of the Premises, including plumbing fixtures and kitchen equipment, in "
        "good repair.",
    ],
    [
        "8. Assignment and Subletting",
        "Tenant shall not assign this Lease or sublet any part of the Premises without "
        "Landlord's prior written consent, which Landlord shall not unreasonably withhold.",
        "9. Insurance",
        "Tenant shall maintain commercial general liability insurance of at least $1,000,000 per "
        "occurrence, naming Landlord as an additional insured.",
        "10. Indemnification",
        # Deliberately one long sentence, as real leases have: the stand-in shortens quotes over
        # 300 characters, and the Source Viewer must still highlight them.
        "Tenant shall indemnify, defend and hold harmless Landlord and its members, managers, "
        "officers, employees and agents from and against any and all claims, demands, losses, "
        "liabilities, damages, judgments, penalties, costs and expenses, including reasonable "
        "attorneys' fees, arising out of or relating to Tenant's use or occupancy of the "
        "Premises, any act or omission of Tenant or its employees, contractors or invitees, or "
        "any breach by Tenant of this Lease, except to the extent caused by Landlord's gross "
        "negligence or willful misconduct.",
    ],
    [
        "11. Default",
        "If Tenant fails to pay rent within ten (10) days after written notice that it is "
        "overdue, Landlord may terminate this Lease and recover possession of the Premises.",
        "12. Governing Law",
        "This Lease is governed by the laws of the State of California.",
        "13. Notices",
        "All notices under this Lease must be in writing and delivered by hand, by courier or by "
        "certified mail to the addresses of the parties stated above.",
    ],
]


@dataclass(frozen=True)
class DemoFile:
    name: str
    content: bytes
    mime: str


def lease() -> DemoFile:
    return DemoFile("Commercial_Lease_Agreement.pdf", make_pdf(LEASE_PAGES), PDF)


def nda() -> DemoFile:
    return DemoFile("Mutual_NDA.docx", make_docx(NDA_PAGES), DOCX)


def scanned() -> DemoFile:
    """No text layer, like a scan: fails until the AI layer adds OCR."""
    return DemoFile("Scanned_Exhibit_A.pdf", make_blank_pdf(3), PDF)


def all_files() -> list[DemoFile]:
    return [lease(), nda(), scanned()]
