/**
 * Seed documents and their page text. All content is fictional and written for the demo.
 * Citations in the mock knowledge base quote this text verbatim, so the Source Viewer can
 * highlight the exact excerpt.
 */
import type { LegalDocument } from '@/api/types';

export const DOC = {
  lease: 'doc_lease',
  nda: 'doc_nda',
  opinion: 'doc_opinion',
  msa: 'doc_msa',
  corrupt: 'doc_corrupt',
  employment: 'doc_employment', // deleted before the demo starts (FR-21)
} as const;

type SeedDoc = Omit<LegalDocument, 'uploadedAt'> & { uploadedDaysAgo: number };

export const SEED_DOCUMENTS: SeedDoc[] = [
  {
    id: DOC.lease,
    name: 'Commercial_Lease_Agreement.pdf',
    type: 'pdf',
    sizeBytes: 1_284_000,
    pages: 24,
    status: 'ready',
    stage: null,
    progress: null,
    isScanned: false,
    warnings: [],
    error: null,
    uploadedDaysAgo: 2,
  },
  {
    id: DOC.nda,
    name: 'Mutual_NDA.docx',
    type: 'docx',
    sizeBytes: 86_500,
    pages: 6,
    status: 'ready',
    stage: null,
    progress: null,
    isScanned: false,
    warnings: [],
    error: null,
    uploadedDaysAgo: 3,
  },
  {
    id: DOC.opinion,
    name: 'Smith_v_Jones_Opinion.pdf',
    type: 'pdf',
    sizeBytes: 4_920_000,
    pages: 12,
    status: 'ready',
    stage: null,
    progress: null,
    isScanned: true,
    warnings: ['Low OCR confidence on pages 3 and 9. Check citations from those pages.'],
    error: null,
    uploadedDaysAgo: 6,
  },
  {
    id: DOC.corrupt,
    name: 'Engagement_Letter_corrupt.pdf',
    type: 'pdf',
    sizeBytes: 412_000,
    pages: null,
    status: 'failed',
    stage: null,
    progress: null,
    isScanned: false,
    warnings: [],
    error: 'Could not read this file. It may be corrupted or password-protected.',
    uploadedDaysAgo: 1,
  },
];

/** Name of the document deleted before the demo (referenced by an old conversation). */
export const DELETED_DOC_NAME = 'Employment_Agreement_2023.pdf';

type PageMap = Record<number, string[]>;

// ---------------------------------------------------------------- Commercial lease (digital)

const LEASE_PAGES: PageMap = {
  1: [
    'COMMERCIAL LEASE AGREEMENT',
    'This Commercial Lease Agreement (the "Lease") is entered into as of March 1, 2025 (the "Effective Date") by and between Harborview Properties LLC, a Delaware limited liability company ("Landlord"), and Brightline Analytics, Inc., a California corporation ("Tenant").',
    'Landlord leases to Tenant approximately 8,400 rentable square feet on the fourth floor of 220 Harbor Street, San Francisco, California (the "Premises"), together with the non-exclusive right to use the common areas of the building.',
  ],
  3: [
    'Section 3. Term',
    '3.1 Initial Term. The initial term of this Lease shall be sixty (60) months, commencing on April 1, 2025 (the "Commencement Date") and expiring on March 31, 2030, unless sooner terminated as provided herein.',
    '3.2 Option to Extend. Tenant shall have one (1) option to extend the term for an additional period of five (5) years, exercisable by written notice to Landlord not less than nine (9) months prior to the expiration of the initial term.',
  ],
  4: [
    'Section 4. Rent',
    '4.1 Base Rent. Base Rent shall be $46,200 per month for the first lease year, payable in advance on the first day of each calendar month.',
    '4.2 Annual Adjustment. Base Rent shall increase by three percent (3%) on each anniversary of the Commencement Date.',
    '4.4 Late Charge. Any installment of Rent not received within five (5) days after its due date shall bear a late charge equal to five percent (5%) of the overdue amount.',
  ],
  5: [
    'Section 5. Security Deposit',
    '5.1 Amount. Tenant shall deposit with Landlord the sum of $138,600, equal to three (3) months of Base Rent, as security for the full and faithful performance of Tenant\'s obligations under this Lease.',
    '5.2 Return. Landlord shall return any unapplied portion of the security deposit within thirty (30) days after the expiration of the term.',
  ],
  9: [
    'Section 9. Maintenance and Repairs',
    '9.2 Tenant\'s Obligations. Tenant shall, at its sole cost, keep the interior of the Premises in good condition and repair, excluding structural elements, the roof and building systems, which remain Landlord\'s responsibility.',
  ],
  14: [
    'Section 14. Assignment and Subletting',
    '14.1 Consent Required. Tenant shall not assign this Lease or sublet all or any part of the Premises without Landlord\'s prior written consent, which consent shall not be unreasonably withheld, conditioned or delayed.',
    '14.3 Permitted Transfers. Notwithstanding Section 14.1, Tenant may assign this Lease to an affiliate or a successor by merger without Landlord\'s consent, provided Tenant gives Landlord written notice within fifteen (15) days after the transfer.',
  ],
  18: [
    'Section 18. Default and Termination',
    '18.1 Termination for Default. Either party may terminate this Lease upon a material default by the other party that remains uncured thirty (30) days after written notice describing the default in reasonable detail.',
    '18.3 Early Termination Option. Tenant may terminate this Lease effective as of the last day of the thirty-sixth (36th) month by giving Landlord at least six (6) months\' prior written notice and paying a termination fee equal to four (4) months of then-current Base Rent.',
  ],
  20: [
    'Section 20. Insurance',
    '20.1 Liability Insurance. Tenant shall maintain commercial general liability insurance with limits of not less than $2,000,000 per occurrence, naming Landlord as an additional insured.',
  ],
  22: [
    'Section 22. Miscellaneous',
    '22.4 Governing Law. This Lease shall be governed by and construed in accordance with the laws of the State of California.',
  ],
  24: [
    'IN WITNESS WHEREOF, the parties have executed this Lease as of the Effective Date.',
    'LANDLORD: Harborview Properties LLC. By: Margaret Ellis, Managing Member.',
    'TENANT: Brightline Analytics, Inc. By: Samuel Ortiz, Chief Executive Officer.',
  ],
};

const LEASE_FILLER: Record<number, string> = {
  2: 'Definitions',
  6: 'Operating Expenses',
  7: 'Utilities and Services',
  8: 'Use of Premises',
  10: 'Alterations',
  11: 'Landlord\'s Access',
  12: 'Signage',
  13: 'Parking',
  15: 'Indemnification',
  16: 'Damage and Destruction',
  17: 'Condemnation',
  19: 'Surrender of Premises',
  21: 'Notices',
  23: 'Brokers',
};

// ---------------------------------------------------------------- Mutual NDA (docx)

const NDA_PAGES: PageMap = {
  1: [
    'MUTUAL NON-DISCLOSURE AGREEMENT',
    'This Mutual Non-Disclosure Agreement (the "Agreement") is made as of January 15, 2026 (the "Effective Date") between Northwind Legal Tech, Inc. ("Northwind") and Calder & Reyes LLP ("Calder"), each a "Party".',
    '1. Purpose. The Parties wish to evaluate a potential collaboration on document-automation software (the "Purpose").',
  ],
  2: [
    '2. Confidential Information. "Confidential Information" means all non-public information disclosed by a Party, in any form, that is marked confidential or would reasonably be understood to be confidential given its nature and the circumstances of disclosure.',
    '3. Exclusions. Confidential Information does not include information that (a) is or becomes publicly available through no fault of the Receiving Party; (b) was known to the Receiving Party before disclosure; (c) is independently developed without use of the Disclosing Party\'s information; or (d) is lawfully received from a third party without restriction.',
  ],
  3: [
    '4. Term. This Agreement shall remain in effect for three (3) years from the Effective Date. The confidentiality obligations shall survive for five (5) years following expiration or termination of this Agreement.',
    '5. Use Restrictions. The Receiving Party shall use Confidential Information solely for the Purpose and shall limit access to its employees and advisors who need to know it for the Purpose.',
  ],
  4: [
    '6. Return of Materials. Upon written request, the Receiving Party shall promptly return or destroy all Confidential Information and certify such destruction in writing within ten (10) business days.',
    '7. Remedies. Each Party acknowledges that unauthorized disclosure may cause irreparable harm, and the Disclosing Party shall be entitled to seek injunctive relief without posting a bond, in addition to any other remedies available at law.',
  ],
  5: [
    '8. No License. Nothing in this Agreement grants either Party any license or right in the other Party\'s intellectual property.',
    '9. Governing Law. This Agreement shall be governed by the laws of the State of New York, and the Parties consent to the exclusive jurisdiction of the state and federal courts located in New York County.',
  ],
  6: [
    'IN WITNESS WHEREOF, the Parties have executed this Agreement as of the Effective Date.',
    'NORTHWIND LEGAL TECH, INC. By: Priya Raman, General Counsel.',
    'CALDER & REYES LLP. By: Thomas Calder, Managing Partner.',
  ],
};

// ---------------------------------------------------------------- Court opinion (scanned, OCR)

const OPINION_PAGES: PageMap = {
  1: [
    'IN THE COURT OF APPEAL OF THE STATE OF CALIFORNIA, FIRST APPELLATE DISTRICT',
    'DANIEL SMITH, Plaintiff and Appellant, v. RACHEL JONES, Defendant and Respondent.',
    'No. A165432. Filed June 12, 2025. Appeal from the Superior Court of Alameda County.',
  ],
  2: [
    'I. BACKGROUND',
    'Smith and Jones entered into a written agreement in 2021 under which Jones would develop a custom inventory system for Smith\'s retail business for a fixed fee of $85,000.',
    'The system was delivered eight months late and, according to Smith, never functioned as specified. Smith alleges that Jones stopped responding to repair requests after receiving final payment.',
  ],
  4: [
    'II. PROCEDURAL HISTORY',
    'Smith sued for breach of contract and fraud. The trial court granted summary judgment for Jones, concluding that Smith\'s claims were barred by the limitation-of-liability clause in the agreement.',
  ],
  6: [
    'III. ISSUE PRESENTED',
    'The question presented is whether a limitation-of-liability clause bars recovery for a party\'s willful failure to perform, as opposed to negligent performance.',
  ],
  8: [
    'IV. DISCUSSION',
    'We hold that, under Civil Code section 1668, a contractual clause cannot exempt a party from liability for its own willful injury to the property of another or for an intentional failure to perform.',
    'Because triable issues of fact exist as to whether Jones\'s nonperformance was willful, summary judgment was improper.',
  ],
  11: [
    'V. DISPOSITION',
    'The judgment is reversed, and the matter is remanded to the trial court for further proceedings consistent with this opinion. Smith shall recover his costs on appeal.',
  ],
};

const OPINION_FILLER: Record<number, string> = {
  3: 'Background (continued)',
  5: 'Standard of Review',
  7: 'Discussion: Contract Interpretation',
  9: 'Discussion: Civil Code Section 1668',
  10: 'Discussion: Remaining Claims',
  12: 'Concurring Opinion',
};

const SEED_PAGES: Record<string, { pages: PageMap; filler: Record<number, string>; total: number }> = {
  [DOC.lease]: { pages: LEASE_PAGES, filler: LEASE_FILLER, total: 24 },
  [DOC.nda]: { pages: NDA_PAGES, filler: {}, total: 6 },
  [DOC.opinion]: { pages: OPINION_PAGES, filler: OPINION_FILLER, total: 12 },
};

/** Returns the paragraphs for a page of a seeded document, or null if not seeded. */
export function seededPage(documentId: string, page: number): string[] | null {
  const doc = SEED_PAGES[documentId];
  if (!doc || page < 1 || page > doc.total) return null;
  const explicit = doc.pages[page];
  if (explicit) return explicit;
  const heading = doc.filler[page] ?? 'Additional Provisions';
  return [
    heading,
    `The provisions on this page address ${heading.toLowerCase()} and should be read together with the remaining terms of the document.`,
    'This page is placeholder text in the Legal Lens demo. The pages cited in the sample answers contain the substantive terms.',
  ];
}

/** Text for pages of documents uploaded during the demo (the mock cannot really read files). */
export function simulatedPage(name: string, page: number): string[] {
  return [
    `${name} — page ${page}`,
    'Demo mode: Legal Lens is running against a mock backend, so the text of newly uploaded files is simulated rather than extracted.',
    'Connect the FastAPI backend to see real extracted text, OCR output and citations for this document.',
  ];
}

export const OCR_LOW_CONFIDENCE_PAGES: Record<string, number[]> = {
  [DOC.opinion]: [3, 9],
};
