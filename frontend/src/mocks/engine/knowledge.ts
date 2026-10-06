/**
 * Canned "retrieval results" for the seeded documents. Each entry stands in for what the real
 * RAG pipeline (hybrid search → re-rank → grounded generation) would return.
 * Every `quote` must appear verbatim on its page (enforced by knowledge.test.ts).
 */
import { DOC } from '../data/documents';

export interface CiteRef {
  page: number;
  section: string | null;
  quote: string;
}

export interface KnowledgeEntry {
  /** Lower-case fragments; matched as substrings of the (rewritten) query. */
  keywords: string[];
  answer: string;
  cites: CiteRef[];
}

export const KNOWLEDGE: Record<string, KnowledgeEntry[]> = {
  [DOC.lease]: [
    {
      keywords: ['terminat', 'early', 'end the lease', 'get out', 'break', 'cancel', 'exit'],
      answer:
        'Yes. The Tenant has a one-time **early termination option**: it may end the Lease effective as of the last day of the **36th month**, provided it gives at least **six months\' prior written notice** and pays a **termination fee equal to four months of then-current Base Rent** [1].\n\nSeparately, **either party** may terminate for a **material default** that remains uncured **30 days** after written notice describing the default [2].',
      cites: [
        {
          page: 18,
          section: '§18.3',
          quote:
            "Tenant may terminate this Lease effective as of the last day of the thirty-sixth (36th) month by giving Landlord at least six (6) months' prior written notice and paying a termination fee equal to four (4) months of then-current Base Rent.",
        },
        {
          page: 18,
          section: '§18.1',
          quote:
            'Either party may terminate this Lease upon a material default by the other party that remains uncured thirty (30) days after written notice describing the default in reasonable detail.',
        },
      ],
    },
    {
      keywords: ['notice', 'how much notice', 'required', 'period', 'in advance', 'deadline'],
      answer:
        'For the early termination option, the Tenant must give the Landlord **at least six (6) months\' prior written notice**, and the termination can only take effect on the **last day of the 36th month** (March 31, 2028, counting from the April 1, 2025 Commencement Date) [1].\n\nFor termination based on a default, the notice must describe the default **in reasonable detail**, and the other party then has **30 days** to cure it [2].',
      cites: [
        {
          page: 18,
          section: '§18.3',
          quote: "by giving Landlord at least six (6) months' prior written notice",
        },
        {
          page: 18,
          section: '§18.1',
          quote:
            'remains uncured thirty (30) days after written notice describing the default in reasonable detail',
        },
      ],
    },
    {
      keywords: ['rent', 'monthly', 'pay', 'payment', 'cost', 'price', 'escalat', 'increase', 'late'],
      answer:
        'Base Rent is **$46,200 per month** for the first lease year, payable in advance on the first day of each month [1]. It **increases by 3%** on each anniversary of the Commencement Date [2].\n\nRent received more than **five days late** incurs a **late charge of 5%** of the overdue amount [3].',
      cites: [
        {
          page: 4,
          section: '§4.1',
          quote:
            'Base Rent shall be $46,200 per month for the first lease year, payable in advance on the first day of each calendar month.',
        },
        {
          page: 4,
          section: '§4.2',
          quote:
            'Base Rent shall increase by three percent (3%) on each anniversary of the Commencement Date.',
        },
        {
          page: 4,
          section: '§4.4',
          quote:
            'shall bear a late charge equal to five percent (5%) of the overdue amount',
        },
      ],
    },
    {
      keywords: ['deposit', 'security'],
      answer:
        'The Tenant must deposit **$138,600**, equal to **three months of Base Rent**, as security for its obligations [1]. Any unapplied portion is returned within **30 days** after the term expires [2].',
      cites: [
        {
          page: 5,
          section: '§5.1',
          quote:
            'Tenant shall deposit with Landlord the sum of $138,600, equal to three (3) months of Base Rent',
        },
        {
          page: 5,
          section: '§5.2',
          quote:
            'Landlord shall return any unapplied portion of the security deposit within thirty (30) days after the expiration of the term.',
        },
      ],
    },
    {
      keywords: ['renew', 'extend', 'extension', 'option to'],
      answer:
        'The Tenant has **one option to extend** the term for an **additional five years**. It must exercise the option by written notice **at least nine months before** the initial term expires [1].',
      cites: [
        {
          page: 3,
          section: '§3.2',
          quote:
            'Tenant shall have one (1) option to extend the term for an additional period of five (5) years, exercisable by written notice to Landlord not less than nine (9) months prior to the expiration of the initial term.',
        },
      ],
    },
    {
      keywords: ['term', 'how long', 'expire', 'expiration', 'commenc', 'start', 'length', 'duration'],
      answer:
        'The initial term is **60 months**, running from **April 1, 2025** (the Commencement Date) to **March 31, 2030**, unless terminated earlier [1]. The Tenant may extend it once for **five more years** [2].',
      cites: [
        {
          page: 3,
          section: '§3.1',
          quote:
            'The initial term of this Lease shall be sixty (60) months, commencing on April 1, 2025 (the "Commencement Date") and expiring on March 31, 2030',
        },
        {
          page: 3,
          section: '§3.2',
          quote: 'one (1) option to extend the term for an additional period of five (5) years',
        },
      ],
    },
    {
      keywords: ['assign', 'sublet', 'sublease', 'transfer', 'merger', 'affiliate'],
      answer:
        'The Tenant needs the Landlord\'s **prior written consent** to assign or sublet, but the Landlord **may not unreasonably withhold, condition or delay** that consent [1].\n\nThere is a carve-out: the Tenant may assign to an **affiliate or a successor by merger without consent**, as long as it notifies the Landlord within **15 days** after the transfer [2].',
      cites: [
        {
          page: 14,
          section: '§14.1',
          quote:
            "Tenant shall not assign this Lease or sublet all or any part of the Premises without Landlord's prior written consent, which consent shall not be unreasonably withheld, conditioned or delayed.",
        },
        {
          page: 14,
          section: '§14.3',
          quote:
            "Tenant may assign this Lease to an affiliate or a successor by merger without Landlord's consent",
        },
      ],
    },
    {
      keywords: ['repair', 'maintenance', 'maintain', 'roof', 'structural', 'hvac', 'building system'],
      answer:
        'The Tenant maintains the **interior** of the Premises at its own cost. **Structural elements, the roof and building systems** remain the **Landlord\'s responsibility** [1].',
      cites: [
        {
          page: 9,
          section: '§9.2',
          quote:
            "Tenant shall, at its sole cost, keep the interior of the Premises in good condition and repair, excluding structural elements, the roof and building systems, which remain Landlord's responsibility.",
        },
      ],
    },
    {
      keywords: ['insurance', 'insured', 'coverage'],
      answer:
        'The Tenant must carry **commercial general liability insurance** of at least **$2,000,000 per occurrence**, naming the Landlord as an **additional insured** [1].',
      cites: [
        {
          page: 20,
          section: '§20.1',
          quote:
            'Tenant shall maintain commercial general liability insurance with limits of not less than $2,000,000 per occurrence, naming Landlord as an additional insured.',
        },
      ],
    },
    {
      keywords: ['governing law', 'which law', 'jurisdiction', 'california law', 'law govern'],
      answer: 'The Lease is governed by the laws of the **State of California** [1].',
      cites: [
        {
          page: 22,
          section: '§22.4',
          quote:
            'This Lease shall be governed by and construed in accordance with the laws of the State of California.',
        },
      ],
    },
    {
      keywords: ['parties', 'who is the', 'who are', 'square feet', 'address', 'where is', 'located', 'size of'],
      answer:
        'The Landlord is **Harborview Properties LLC** (a Delaware LLC) and the Tenant is **Brightline Analytics, Inc.** (a California corporation) [1]. The Premises are about **8,400 rentable square feet** on the fourth floor of **220 Harbor Street, San Francisco** [2].',
      cites: [
        {
          page: 1,
          section: 'Preamble',
          quote:
            'by and between Harborview Properties LLC, a Delaware limited liability company ("Landlord"), and Brightline Analytics, Inc., a California corporation ("Tenant").',
        },
        {
          page: 1,
          section: 'Premises',
          quote:
            'approximately 8,400 rentable square feet on the fourth floor of 220 Harbor Street, San Francisco, California',
        },
      ],
    },
  ],

  [DOC.nda]: [
    {
      keywords: ['how long', 'term', 'last', 'duration', 'surviv', 'years', 'expire'],
      answer:
        'The Agreement itself runs for **three years** from the Effective Date (January 15, 2026). The **confidentiality obligations survive for five more years** after it expires or is terminated [1], so protection can last up to **eight years** in total.',
      cites: [
        {
          page: 3,
          section: '§4',
          quote:
            'This Agreement shall remain in effect for three (3) years from the Effective Date. The confidentiality obligations shall survive for five (5) years following expiration or termination of this Agreement.',
        },
      ],
    },
    {
      keywords: ['exclu', 'except', 'not covered', 'publicly', 'independently', 'carve'],
      answer:
        'Four categories are excluded: information that **(a)** becomes public through no fault of the recipient, **(b)** was already known to the recipient, **(c)** is independently developed, or **(d)** is lawfully received from a third party without restriction [1].',
      cites: [
        {
          page: 2,
          section: '§3',
          quote:
            'is or becomes publicly available through no fault of the Receiving Party; (b) was known to the Receiving Party before disclosure;',
        },
      ],
    },
    {
      keywords: ['confidential information', 'define', 'definition', 'what counts', 'covered', 'mean'],
      answer:
        '"Confidential Information" covers **all non-public information** disclosed by a Party, in any form, that is either **marked confidential** or would **reasonably be understood to be confidential** given its nature and the circumstances [1].',
      cites: [
        {
          page: 2,
          section: '§2',
          quote:
            '"Confidential Information" means all non-public information disclosed by a Party, in any form, that is marked confidential or would reasonably be understood to be confidential',
        },
      ],
    },
    {
      keywords: ['return', 'destroy', 'destruction', 'certif'],
      answer:
        'On written request, the recipient must **return or destroy** all Confidential Information and **certify the destruction in writing within 10 business days** [1].',
      cites: [
        {
          page: 4,
          section: '§6',
          quote:
            'the Receiving Party shall promptly return or destroy all Confidential Information and certify such destruction in writing within ten (10) business days.',
        },
      ],
    },
    {
      keywords: ['remed', 'injunct', 'breach', 'bond', 'damages', 'enforce'],
      answer:
        'The Parties agree that unauthorized disclosure may cause **irreparable harm**, and the disclosing Party may seek **injunctive relief without posting a bond**, in addition to other legal remedies [1].',
      cites: [
        {
          page: 4,
          section: '§7',
          quote:
            'the Disclosing Party shall be entitled to seek injunctive relief without posting a bond',
        },
      ],
    },
    {
      keywords: ['governing', 'which law', 'jurisdiction', 'court', 'new york', 'venue'],
      answer:
        'New York law governs, and the Parties consent to the **exclusive jurisdiction** of the state and federal courts in **New York County** [1].',
      cites: [
        {
          page: 5,
          section: '§9',
          quote:
            'This Agreement shall be governed by the laws of the State of New York, and the Parties consent to the exclusive jurisdiction of the state and federal courts located in New York County.',
        },
      ],
    },
    {
      keywords: ['parties', 'who', 'purpose', 'between', 'why'],
      answer:
        'The Agreement is between **Northwind Legal Tech, Inc.** and **Calder & Reyes LLP** [1], entered into so they can evaluate a potential **collaboration on document-automation software** [2].',
      cites: [
        {
          page: 1,
          section: 'Preamble',
          quote:
            'between Northwind Legal Tech, Inc. ("Northwind") and Calder & Reyes LLP ("Calder")',
        },
        {
          page: 1,
          section: '§1',
          quote: 'evaluate a potential collaboration on document-automation software',
        },
      ],
    },
  ],

  [DOC.opinion]: [
    {
      keywords: ['1668', 'civil code', 'statute', 'willful', 'limitation of liability', 'limitation-of-liability', 'exculpat'],
      answer:
        'The court held that under **Civil Code section 1668**, a contract clause **cannot exempt a party from liability** for its own **willful injury** or an **intentional failure to perform** [1]. A limitation-of-liability clause therefore cannot shield willful nonperformance.',
      cites: [
        {
          page: 8,
          section: 'IV. Discussion',
          quote:
            'under Civil Code section 1668, a contractual clause cannot exempt a party from liability for its own willful injury to the property of another or for an intentional failure to perform.',
        },
      ],
    },
    {
      keywords: ['hold', 'held', 'rule', 'decid', 'outcome', 'result', 'win', 'conclu'],
      answer:
        'The Court of Appeal **reversed** the summary judgment for Jones. It held that a contractual clause cannot exempt a party from liability for an **intentional failure to perform** (Civil Code §1668) [1], and found **triable issues of fact** as to whether Jones\'s nonperformance was willful [2]. The case was **remanded**, and Smith recovers his costs on appeal [3].',
      cites: [
        {
          page: 8,
          section: 'IV. Discussion',
          quote:
            'a contractual clause cannot exempt a party from liability for its own willful injury to the property of another or for an intentional failure to perform.',
        },
        {
          page: 8,
          section: 'IV. Discussion',
          quote:
            "Because triable issues of fact exist as to whether Jones's nonperformance was willful, summary judgment was improper.",
        },
        {
          page: 11,
          section: 'V. Disposition',
          quote:
            'The judgment is reversed, and the matter is remanded to the trial court for further proceedings consistent with this opinion.',
        },
      ],
    },
    {
      keywords: ['fact', 'background', 'happen', 'agreement', 'contract', 'fee', 'late', 'inventory'],
      answer:
        'In 2021, Jones agreed to build a **custom inventory system** for Smith\'s retail business for a **fixed fee of $85,000** [1]. The system was delivered **eight months late** and, according to Smith, **never worked as specified**. Smith also alleges Jones stopped responding to repair requests after final payment [2].',
      cites: [
        {
          page: 2,
          section: 'I. Background',
          quote:
            "Jones would develop a custom inventory system for Smith's retail business for a fixed fee of $85,000.",
        },
        {
          page: 2,
          section: 'I. Background',
          quote:
            'The system was delivered eight months late and, according to Smith, never functioned as specified.',
        },
      ],
    },
    {
      keywords: ['trial court', 'summary judgment', 'procedur', 'below', 'lower court'],
      answer:
        'Smith sued for **breach of contract and fraud**. The trial court granted **summary judgment for Jones**, holding the claims were barred by the agreement\'s **limitation-of-liability clause** [1].',
      cites: [
        {
          page: 4,
          section: 'II. Procedural History',
          quote:
            "The trial court granted summary judgment for Jones, concluding that Smith's claims were barred by the limitation-of-liability clause in the agreement.",
        },
      ],
    },
    {
      keywords: ['issue', 'question', 'presented'],
      answer:
        'The issue was whether a **limitation-of-liability clause** bars recovery for a party\'s **willful failure to perform**, as opposed to negligent performance [1].',
      cites: [
        {
          page: 6,
          section: 'III. Issue Presented',
          quote:
            "whether a limitation-of-liability clause bars recovery for a party's willful failure to perform, as opposed to negligent performance.",
        },
      ],
    },
  ],
};

// ---------------------------------------------------------------- summaries

export interface CannedLongform {
  content: string;
  cites: CiteRef[];
}

export const SUMMARIES: Record<string, CannedLongform> = {
  [DOC.lease]: {
    content: `### Document type & purpose
A **commercial office lease** for space in San Francisco, dated March 1, 2025 [1].

### Parties
- **Landlord:** Harborview Properties LLC (Delaware LLC)
- **Tenant:** Brightline Analytics, Inc. (California corporation) [1]

### Key dates & deadlines
- **Term:** April 1, 2025 – March 31, 2030 (60 months) [2]
- **Renewal notice:** at least 9 months before expiry [3]
- **Early termination:** effective end of month 36, with 6 months' notice [4]

### Key terms & obligations
- **Base Rent:** $46,200/month in year one, rising **3% a year** [5]
- **Security deposit:** $138,600 (three months' rent) [6]
- **Repairs:** Tenant handles the interior; Landlord keeps the structure, roof and building systems [7]

### Notable risks
- The early termination fee equals **four months of then-current rent** [4]
- Assignment needs consent, though it **cannot be unreasonably withheld** [8]

### Plain-language overview
A five-year office lease with one five-year renewal, predictable 3% annual rent increases, and a single exit point after year three at a cost of four months' rent.`,
    cites: [
      { page: 1, section: 'Preamble', quote: 'This Commercial Lease Agreement (the "Lease") is entered into as of March 1, 2025' },
      { page: 3, section: '§3.1', quote: 'The initial term of this Lease shall be sixty (60) months, commencing on April 1, 2025' },
      { page: 3, section: '§3.2', quote: 'not less than nine (9) months prior to the expiration of the initial term' },
      { page: 18, section: '§18.3', quote: "Tenant may terminate this Lease effective as of the last day of the thirty-sixth (36th) month by giving Landlord at least six (6) months' prior written notice" },
      { page: 4, section: '§4.1', quote: 'Base Rent shall be $46,200 per month for the first lease year' },
      { page: 5, section: '§5.1', quote: 'Tenant shall deposit with Landlord the sum of $138,600' },
      { page: 9, section: '§9.2', quote: 'excluding structural elements, the roof and building systems' },
      { page: 14, section: '§14.1', quote: 'which consent shall not be unreasonably withheld, conditioned or delayed' },
    ],
  },
  [DOC.nda]: {
    content: `### Document type & purpose
A **mutual non-disclosure agreement** to protect information exchanged while evaluating a document-automation collaboration [1].

### Parties
- **Northwind Legal Tech, Inc.**
- **Calder & Reyes LLP** [2]

### Key dates & deadlines
- **Effective Date:** January 15, 2026 [2]
- **Term:** 3 years; confidentiality survives **5 more years** [3]
- **Return or destroy materials:** certify within **10 business days** of a request [4]

### Key terms & obligations
- Broad definition of Confidential Information, covering marked and "reasonably understood" information [5]
- Four standard exclusions (public, previously known, independently developed, third party) [6]

### Notable risks
- **Injunctive relief without a bond** is available to the disclosing party [7]
- _Not found in document:_ a non-solicitation clause or a limitation of liability

### Plain-language overview
A balanced, fairly standard mutual NDA under **New York law** [8], with long-lived confidentiality obligations and strong injunction rights.`,
    cites: [
      { page: 1, section: '§1', quote: 'evaluate a potential collaboration on document-automation software' },
      { page: 1, section: 'Preamble', quote: 'is made as of January 15, 2026 (the "Effective Date") between Northwind Legal Tech, Inc. ("Northwind") and Calder & Reyes LLP ("Calder")' },
      { page: 3, section: '§4', quote: 'The confidentiality obligations shall survive for five (5) years following expiration or termination of this Agreement.' },
      { page: 4, section: '§6', quote: 'certify such destruction in writing within ten (10) business days' },
      { page: 2, section: '§2', quote: 'that is marked confidential or would reasonably be understood to be confidential' },
      { page: 2, section: '§3', quote: 'is independently developed without use of the Disclosing Party\'s information' },
      { page: 4, section: '§7', quote: 'the Disclosing Party shall be entitled to seek injunctive relief without posting a bond' },
      { page: 5, section: '§9', quote: 'This Agreement shall be governed by the laws of the State of New York' },
    ],
  },
  [DOC.opinion]: {
    content: `### Document type & purpose
A **California Court of Appeal opinion** (First Appellate District), No. A165432, filed June 12, 2025 [1].

### Parties
- **Daniel Smith**, plaintiff and appellant
- **Rachel Jones**, defendant and respondent [2]

### Key dates & deadlines
- **2021:** software development agreement signed [3]
- **June 12, 2025:** opinion filed [1]

### Key terms & holdings
- Civil Code §1668 bars contract clauses that exempt a party from liability for **willful injury or intentional nonperformance** [4]
- Triable issues existed on willfulness, so **summary judgment was improper** [5]

### Notable risks
- Limitation-of-liability clauses **may not protect** against claims of willful nonperformance
- _Not found in document:_ the amount of damages ultimately awarded

### Plain-language overview
Smith paid $85,000 for software that arrived late and did not work. The trial court said the contract capped his claims. The appeals court disagreed for willful failures, **reversed**, and sent the case back [6].`,
    cites: [
      { page: 1, section: 'Caption', quote: 'No. A165432. Filed June 12, 2025.' },
      { page: 1, section: 'Caption', quote: 'DANIEL SMITH, Plaintiff and Appellant, v. RACHEL JONES, Defendant and Respondent.' },
      { page: 2, section: 'I. Background', quote: 'Smith and Jones entered into a written agreement in 2021' },
      { page: 8, section: 'IV. Discussion', quote: 'a contractual clause cannot exempt a party from liability for its own willful injury to the property of another or for an intentional failure to perform.' },
      { page: 8, section: 'IV. Discussion', quote: 'summary judgment was improper' },
      { page: 11, section: 'V. Disposition', quote: 'The judgment is reversed, and the matter is remanded to the trial court' },
    ],
  },
};

// ---------------------------------------------------------------- drafts

export const NDA_MEMO: CannedLongform = {
  content: `**MEMORANDUM**

**To:** [CONFIRM: client contact at Calder & Reyes LLP]\\
**From:** [CONFIRM: attorney name]\\
**Date:** {{today}}\\
**Re:** Risk review of the Mutual Non-Disclosure Agreement with Northwind Legal Tech, Inc.

### 1. Question presented
Does the Mutual NDA dated January 15, 2026 adequately protect our client's information during the proposed collaboration, and what risks should be raised before signing?

### 2. Short answer
Mostly yes. The NDA uses a broad definition of Confidential Information [1] and long survival periods [2], but it lacks a non-solicitation clause and allows injunctive relief **without a bond** in both directions [3].

### 3. Key provisions
- **Term:** three years, with confidentiality surviving five years after expiry [2].
- **Exclusions:** the four customary carve-outs, including independently developed information [4].
- **Return of materials:** written certification within ten business days of a request [5].
- **Governing law:** New York, with exclusive jurisdiction in New York County [6].

### 4. Risks and recommendations
1. **No non-solicitation.** Consider adding a 12-month mutual non-solicit. Enforceability standards for such clauses vary by state [CITATION NEEDED].
2. **Injunctions without bond.** Mutual, so acceptable, but confirm the client is comfortable being subject to the same remedy [3].
3. **Residuals.** The NDA is silent on information retained in unaided memory. Decide whether to propose a residuals clause [CONFIRM: client's position].

### 5. Next steps
Send a markup with the non-solicitation and residuals language by [CONFIRM: date].`,
  cites: [
    { page: 2, section: '§2', quote: '"Confidential Information" means all non-public information disclosed by a Party, in any form' },
    { page: 3, section: '§4', quote: 'The confidentiality obligations shall survive for five (5) years following expiration or termination of this Agreement.' },
    { page: 4, section: '§7', quote: 'the Disclosing Party shall be entitled to seek injunctive relief without posting a bond' },
    { page: 2, section: '§3', quote: 'is independently developed without use of the Disclosing Party\'s information' },
    { page: 4, section: '§6', quote: 'certify such destruction in writing within ten (10) business days' },
    { page: 5, section: '§9', quote: 'the Parties consent to the exclusive jurisdiction of the state and federal courts located in New York County' },
  ],
};

export const LEASE_MEMO: CannedLongform = {
  content: `**MEMORANDUM**

**To:** [CONFIRM: client contact at Brightline Analytics, Inc.]\\
**From:** [CONFIRM: attorney name]\\
**Date:** {{today}}\\
**Re:** Exit options under the Harborview Properties commercial lease

### 1. Question presented
What options does Brightline have to leave the 220 Harbor Street premises before the term ends on March 31, 2030?

### 2. Short answer
Brightline has one contractual exit: an **early termination option** effective at the end of month 36, on six months' notice and a fee of four months' rent [1]. Otherwise it can assign to an affiliate without consent [2] or seek consent to a third-party assignment, which may not be unreasonably withheld [3].

### 3. Analysis
- **Early termination.** Notice must reach the Landlord by **[CONFIRM: September 30, 2027]** for termination on March 31, 2028 [1].
- **Assignment and subletting.** Consent standard is "not unreasonably withheld, conditioned or delayed" [3]. Case law on what counts as reasonable refusal should be checked [CITATION NEEDED].
- **Default termination.** Available only for an uncured material default after 30 days' notice [4].

### 4. Recommendation
Calendar the termination notice deadline now and estimate the fee at the year-three rent level [CONFIRM: current Base Rent].`,
  cites: [
    { page: 18, section: '§18.3', quote: "Tenant may terminate this Lease effective as of the last day of the thirty-sixth (36th) month by giving Landlord at least six (6) months' prior written notice and paying a termination fee equal to four (4) months of then-current Base Rent." },
    { page: 14, section: '§14.3', quote: "Tenant may assign this Lease to an affiliate or a successor by merger without Landlord's consent" },
    { page: 14, section: '§14.1', quote: 'which consent shall not be unreasonably withheld, conditioned or delayed' },
    { page: 18, section: '§18.1', quote: 'remains uncured thirty (30) days after written notice describing the default in reasonable detail' },
  ],
};

export const CASE_BRIEF: CannedLongform = {
  content: `**CASE BRIEF**

**Case:** Smith v. Jones, No. A165432 (Cal. Ct. App., 1st Dist., June 12, 2025) [1]\\
**Prepared by:** [CONFIRM: attorney name]\\
**Date:** {{today}}

### Facts
Jones agreed in 2021 to build a custom inventory system for Smith's retail business for **$85,000** [2]. It was delivered eight months late and allegedly never worked as specified [3].

### Procedural history
Smith sued for breach of contract and fraud. The trial court granted **summary judgment for Jones** based on the contract's limitation-of-liability clause [4].

### Issue
Does a limitation-of-liability clause bar recovery for a party's **willful** failure to perform, as opposed to negligent performance? [5]

### Holding
No. Under **Civil Code §1668**, a contract cannot exempt a party from liability for an intentional failure to perform [6].

### Reasoning
Because triable issues of fact existed on whether Jones's nonperformance was willful, summary judgment was improper [7]. Related authority applying §1668 to software contracts: [CITATION NEEDED].

### Disposition
**Reversed and remanded.** Smith recovers his costs on appeal [8].

### Significance
Drafters cannot rely on liability caps to shield deliberate nonperformance in California. Review the client's template agreements for exposure [CONFIRM: which templates].`,
  cites: [
    { page: 1, section: 'Caption', quote: 'No. A165432. Filed June 12, 2025.' },
    { page: 2, section: 'I. Background', quote: "Jones would develop a custom inventory system for Smith's retail business for a fixed fee of $85,000." },
    { page: 2, section: 'I. Background', quote: 'The system was delivered eight months late and, according to Smith, never functioned as specified.' },
    { page: 4, section: 'II. Procedural History', quote: 'The trial court granted summary judgment for Jones' },
    { page: 6, section: 'III. Issue Presented', quote: "whether a limitation-of-liability clause bars recovery for a party's willful failure to perform" },
    { page: 8, section: 'IV. Discussion', quote: 'under Civil Code section 1668, a contractual clause cannot exempt a party from liability' },
    { page: 8, section: 'IV. Discussion', quote: "Because triable issues of fact exist as to whether Jones's nonperformance was willful, summary judgment was improper." },
    { page: 11, section: 'V. Disposition', quote: 'Smith shall recover his costs on appeal.' },
  ],
};

export const GENERIC_MEMO = `**MEMORANDUM**

**To:** [CONFIRM: recipient]\\
**From:** [CONFIRM: attorney name]\\
**Date:** {{today}}\\
**Re:** {{topic}}

### 1. Question presented
[CONFIRM: the precise question the client needs answered]

### 2. Short answer
No reference document was selected, so this draft contains structure only. Facts and authorities must be added before use [CITATION NEEDED].

### 3. Background
[CONFIRM: relevant facts, dates and parties]

### 4. Analysis
[CONFIRM: governing law and jurisdiction] [CITATION NEEDED]

### 5. Recommendation
[CONFIRM: recommended course of action]

_Tip: select a Ready document from the library so the draft can quote it with citations._`;
