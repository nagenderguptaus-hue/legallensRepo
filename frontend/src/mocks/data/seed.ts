import type { Conversation, LegalDocument, Message } from '@/api/types';
import type { IngestJob } from '../engine/ingestion';
import { respond } from '../engine/respond';
import { DELETED_DOC_NAME, DOC, SEED_DOCUMENTS } from './documents';

export interface DbState {
  documents: LegalDocument[];
  jobs: Record<string, IngestJob>;
  conversations: Conversation[];
  messages: Message[];
}

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

export function buildSeed(now: number): DbState {
  const documents: LegalDocument[] = SEED_DOCUMENTS.map(({ uploadedDaysAgo, ...doc }) => ({
    ...doc,
    uploadedAt: new Date(now - uploadedDaysAgo * DAY).toISOString(),
  }));
  // A scanned upload that is still being OCR'd when the demo opens.
  documents.unshift({
    id: DOC.msa,
    name: 'Vendor_MSA_scan.pdf',
    type: 'pdf',
    sizeBytes: 3_150_000,
    pages: 14,
    status: 'processing',
    stage: 'validating',
    progress: null,
    isScanned: true,
    warnings: [],
    error: null,
    uploadedAt: new Date(now).toISOString(),
  });

  const byId = (id: string) => documents.find((d) => d.id === id) ?? null;
  const conversations: Conversation[] = [];
  const messages: Message[] = [];

  const addConversation = (
    id: string,
    title: string,
    documentId: string | null,
    startedAgo: number,
    userTurns: string[],
  ) => {
    const document = documentId ? byId(documentId) : null;
    let t = now - startedAgo;
    const previous: string[] = [];
    for (const [i, text] of userTurns.entries()) {
      const r = respond({ message: text, document, previousUserMessages: [...previous] });
      messages.push(
        baseMessage(`${id}_u${i}`, id, 'user', text, t, documentId),
        {
          ...baseMessage(`${id}_a${i}`, id, 'assistant', r.content, t + 25_000, documentId),
          intent: r.intent,
          outcome: r.outcome,
          citations: r.citations,
          suggestions: r.suggestions,
        },
      );
      previous.push(text);
      t += 4 * MIN;
    }
    conversations.push({
      id,
      title,
      documentId,
      documentDeleted: false,
      createdAt: new Date(now - startedAgo).toISOString(),
      updatedAt: new Date(t - 4 * MIN + 25_000).toISOString(),
    });
  };

  addConversation('conv_lease_exit', 'Lease: early termination rights', DOC.lease, 50 * MIN, [
    'Can the tenant terminate the lease early?',
    'What notice is required for that?',
  ]);
  addConversation('conv_nda_term', 'NDA: how long confidentiality lasts', DOC.nda, 3 * HOUR, [
    'How long do the confidentiality obligations last?',
    'Does it cover employee non-solicitation?',
  ]);
  addConversation('conv_opinion_summary', 'Smith v. Jones: summary', DOC.opinion, 26 * HOUR, [
    'Summarize this opinion',
  ]);
  addConversation('conv_nda_memo', 'Memo: NDA risk review', DOC.nda, 30 * HOUR, [
    'Draft a memo on the risks in this NDA for our client',
  ]);
  addConversation('conv_case_brief', 'Case brief: Smith v. Jones', DOC.opinion, 4 * DAY, [
    'Draft a case brief of Smith v. Jones',
  ]);
  addConversation('conv_clarify', 'Getting started', null, 5 * DAY, ['help']);

  // A conversation whose source document was deleted later (FR-21).
  const oldId = 'conv_employment';
  const oldTime = now - 20 * DAY;
  messages.push(
    baseMessage(`${oldId}_u0`, oldId, 'user', 'How long is the non-compete period?', oldTime, DOC.employment),
    {
      ...baseMessage(
        `${oldId}_a0`,
        oldId,
        'assistant',
        'The non-compete lasts **twelve months** after employment ends and applies only within **50 miles** of any company office [1].',
        oldTime + 25_000,
        DOC.employment,
      ),
      intent: 'ask',
      outcome: 'answered',
      citations: [
        {
          index: 1,
          documentId: DOC.employment,
          documentName: DELETED_DOC_NAME,
          page: 7,
          section: '§11.2',
          quote: 'Employee shall not compete within fifty (50) miles of any Company office for twelve (12) months following termination.',
        },
      ],
    },
  );
  conversations.push({
    id: oldId,
    title: 'Employment agreement: non-compete',
    documentId: DOC.employment,
    documentDeleted: true,
    createdAt: new Date(oldTime).toISOString(),
    updatedAt: new Date(oldTime + 25_000).toISOString(),
  });

  return {
    documents,
    jobs: { [DOC.msa]: { startedAt: now, failAt: null } },
    conversations,
    messages,
  };
}

function baseMessage(
  id: string,
  conversationId: string,
  role: Message['role'],
  content: string,
  time: number,
  documentId: string | null,
): Message {
  return {
    id,
    conversationId,
    role,
    content,
    createdAt: new Date(time).toISOString(),
    status: 'complete',
    intent: null,
    outcome: null,
    citations: [],
    suggestions: [],
    documentId,
  };
}
