/**
 * Mock "AI layer": turns a user message into an assistant response (intent, progress steps,
 * markdown content, citations). Pure and synchronous so it can also build the seed data.
 */
import type { Citation, Intent, LegalDocument, Outcome } from '@/api/types';
import { DOC } from '../data/documents';
import {
  CASE_BRIEF,
  type CannedLongform,
  type CiteRef,
  GENERIC_MEMO,
  KNOWLEDGE,
  LEASE_MEMO,
  NDA_MEMO,
  SUMMARIES,
} from './knowledge';
import { detectIntent, isFollowUp } from './intent';

export interface MockResponse {
  intent: Intent;
  outcome: Outcome;
  statusSteps: string[];
  content: string;
  citations: Citation[];
  suggestions: string[];
}

interface RespondInput {
  message: string;
  document: LegalDocument | null;
  /** Previous user messages in this conversation, oldest first. */
  previousUserMessages: string[];
  today?: Date;
}

const CLARIFY_SUGGESTIONS = [
  'Summarize this document',
  'What are the key obligations?',
  'Draft a memo based on this document',
];

export function respond({ message, document, previousUserMessages, today = new Date() }: RespondInput): MockResponse {
  const intent = detectIntent(message);
  const docName = document?.name ?? 'the document';

  if (intent === 'clarify') {
    return {
      intent,
      outcome: 'clarify',
      statusSteps: ['Understanding your request'],
      content: document
        ? `I can help with **${docName}** in a few ways. What would you like to do?`
        : 'I can answer questions about a document, summarize it, or draft a memo or case brief. What would you like to do?',
      citations: [],
      suggestions: CLARIFY_SUGGESTIONS,
    };
  }

  if ((intent === 'ask' || intent === 'summary') && !document) {
    return {
      intent,
      outcome: 'needs_document',
      statusSteps: ['Understanding your request'],
      content:
        intent === 'ask'
          ? 'I answer questions **only from your documents**, so I need one to work with. Upload a PDF or Word file, or pick a Ready document from the library, then ask again.'
          : 'Select or upload a document and I will summarize it section by section, with citations.',
      citations: [],
      suggestions: [],
    };
  }

  if (intent === 'summary' && document) {
    const canned = SUMMARIES[document.id];
    return {
      intent,
      outcome: 'answered',
      statusSteps: [
        `Reading ${docName} section by section`,
        `Summarizing ${document.pages ?? 'all'} pages`,
        'Combining into the summary template',
        'Checking coverage and citations',
      ],
      content: canned ? canned.content : simulatedSummary(docName),
      citations: canned ? toCitations(canned.cites, document) : [],
      suggestions: [],
    };
  }

  if (intent === 'draft') {
    const brief = /\bbrief\b/i.test(message);
    const kind = brief ? 'case brief' : 'memo';
    const canned = pickDraft(document, brief);
    const dateStr = today.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    const content = (canned?.content ?? GENERIC_MEMO)
      .replace('{{today}}', dateStr)
      .replace('{{topic}}', toTopic(message));
    return {
      intent,
      outcome: 'answered',
      statusSteps: [
        `Planning the ${kind} outline`,
        document ? `Gathering facts from ${docName}` : 'No reference document selected',
        'Drafting section by section',
        'Marking facts that need confirmation',
      ],
      content,
      citations: canned && document ? toCitations(canned.cites, document) : [],
      suggestions: [],
    };
  }

  // ---- ask
  const doc = document as LegalDocument;
  const followUp = previousUserMessages.length > 0 && isFollowUp(message);
  const previous = previousUserMessages.at(-1) ?? '';
  const steps = [
    'Understanding your question',
    ...(followUp ? [`Rewriting follow-up with context: “${truncate(previous, 48)}”`] : []),
    `Searching ${docName} (semantic + keyword)`,
    'Re-ranking 20 passages',
    'Writing a grounded answer',
  ];

  const entries = KNOWLEDGE[doc.id];
  if (!entries) {
    return {
      intent,
      outcome: 'answered',
      statusSteps: steps,
      content:
        `This document was uploaded during the demo, so its text is **simulated** by the mock backend [1]. ` +
        'Connect the FastAPI backend to get real answers, or try one of the seeded documents (the lease, the NDA or the Smith v. Jones opinion).',
      citations: [
        {
          index: 1,
          documentId: doc.id,
          documentName: doc.name,
          page: 1,
          section: null,
          quote: 'the text of newly uploaded files is simulated rather than extracted',
        },
      ],
      suggestions: [],
    };
  }

  const current = message.toLowerCase();
  const context = followUp ? previous.toLowerCase() : '';
  let best: { entry: (typeof entries)[number]; score: number } | null = null;
  for (const entry of entries) {
    const inCurrent = entry.keywords.filter((k) => current.includes(k)).length;
    const inContext = entry.keywords.filter((k) => context.includes(k)).length;
    const score = inCurrent * 2 + inContext;
    if (inCurrent > 0 && (!best || score > best.score)) best = { entry, score };
  }

  if (!best) {
    return {
      intent,
      outcome: 'not_found',
      statusSteps: steps,
      content: `I couldn't find this in **${docName}**. None of the retrieved passages scored above the relevance threshold, so I won't guess.`,
      citations: [],
      suggestions: [],
    };
  }

  return {
    intent,
    outcome: 'answered',
    statusSteps: steps,
    content: best.entry.answer,
    citations: toCitations(best.entry.cites, doc),
    suggestions: [],
  };
}

function pickDraft(document: LegalDocument | null, brief: boolean): CannedLongform | null {
  if (!document) return null;
  if (document.id === DOC.opinion) return CASE_BRIEF;
  if (brief) return null;
  if (document.id === DOC.nda) return NDA_MEMO;
  if (document.id === DOC.lease) return LEASE_MEMO;
  return null;
}

function toCitations(cites: CiteRef[], document: LegalDocument): Citation[] {
  return cites.map((c, i) => ({
    index: i + 1,
    documentId: document.id,
    documentName: document.name,
    page: c.page,
    section: c.section,
    quote: c.quote,
  }));
}

function simulatedSummary(name: string): string {
  return `### Document type & purpose
${name} was uploaded during the demo. The mock backend cannot read its contents.

### Parties
_Not found in document._

### Key dates & deadlines
_Not found in document._

### Key terms & obligations
_Not found in document._

### Notable risks
_Not found in document._

### Plain-language overview
Connect the FastAPI backend to summarize real uploads, or try a seeded document.`;
}

function toTopic(message: string): string {
  const cleaned = message.replace(/^(please\s+)?(draft|write|prepare|compose)\s+(me\s+)?(a|an)?\s*/i, '');
  return truncate(cleaned.charAt(0).toUpperCase() + cleaned.slice(1), 80) || 'Legal memorandum';
}

export function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}
