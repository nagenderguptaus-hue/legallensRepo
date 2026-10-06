import { describe, expect, it } from 'vitest';
import type { LegalDocument } from '@/api/types';
import { DOC, SEED_DOCUMENTS, seededPage } from '../data/documents';
import { advance } from './ingestion';
import { detectIntent, isFollowUp } from './intent';
import { CASE_BRIEF, KNOWLEDGE, LEASE_MEMO, NDA_MEMO, SUMMARIES, type CiteRef } from './knowledge';
import { respond } from './respond';

const doc = (id: string): LegalDocument => {
  const { uploadedDaysAgo: _, ...d } = SEED_DOCUMENTS.find((s) => s.id === id)!;
  return { ...d, uploadedAt: new Date().toISOString() };
};

describe('mock citations integrity', () => {
  const check = (documentId: string, cites: CiteRef[]) => {
    for (const c of cites) {
      const text = (seededPage(documentId, c.page) ?? []).join('\n');
      expect(text, `p.${c.page} of ${documentId} should contain: ${c.quote}`).toContain(c.quote);
    }
  };

  it('every knowledge-base quote appears verbatim on its page', () => {
    for (const [documentId, entries] of Object.entries(KNOWLEDGE)) {
      for (const entry of entries) check(documentId, entry.cites);
    }
  });

  it('every summary and draft quote appears verbatim on its page', () => {
    for (const [documentId, summary] of Object.entries(SUMMARIES)) check(documentId, summary.cites);
    check(DOC.nda, NDA_MEMO.cites);
    check(DOC.lease, LEASE_MEMO.cites);
    check(DOC.opinion, CASE_BRIEF.cites);
  });
});

describe('detectIntent', () => {
  it.each([
    ['Summarize this opinion', 'summary'],
    ['Give me an overview of the key terms', 'summary'],
    ['Draft a memo on the NDA risks', 'draft'],
    ['Write a case brief of Smith v. Jones', 'draft'],
    ['help', 'clarify'],
    ['Can the tenant terminate the lease early?', 'ask'],
  ])('%s → %s', (message, intent) => {
    expect(detectIntent(message)).toBe(intent);
  });

  it('flags short pronoun follow-ups for query rewriting', () => {
    expect(isFollowUp('What notice is required for that?')).toBe(true);
    expect(isFollowUp('What is the governing law of the agreement between the parties here today?')).toBe(false);
  });
});

describe('respond', () => {
  it('answers from the document with citations', () => {
    const r = respond({ message: 'Can the tenant sublet the premises?', document: doc(DOC.lease), previousUserMessages: [] });
    expect(r.outcome).toBe('answered');
    expect(r.content).toMatch(/prior written consent/);
    expect(r.citations[0]).toMatchObject({ page: 14, section: '§14.1', index: 1 });
  });

  it('uses conversation context for follow-ups (query editor)', () => {
    const r = respond({
      message: 'What notice is required for that?',
      document: doc(DOC.lease),
      previousUserMessages: ['Can the tenant terminate the lease early?'],
    });
    expect(r.statusSteps.some((s) => s.startsWith('Rewriting follow-up'))).toBe(true);
    expect(r.content).toMatch(/six \(6\) months/);
  });

  it('refuses to guess when nothing relevant is found', () => {
    const r = respond({ message: 'Is there a non-solicitation clause?', document: doc(DOC.nda), previousUserMessages: [] });
    expect(r.outcome).toBe('not_found');
    expect(r.citations).toEqual([]);
  });

  it('asks for a document before answering or summarizing', () => {
    expect(respond({ message: 'What is the rent?', document: null, previousUserMessages: [] }).outcome).toBe('needs_document');
    expect(respond({ message: 'Summarize it', document: null, previousUserMessages: [] }).outcome).toBe('needs_document');
  });

  it('drafts with visible placeholders instead of invented citations', () => {
    const r = respond({ message: 'Draft a memo on the NDA risks', document: doc(DOC.nda), previousUserMessages: [] });
    expect(r.intent).toBe('draft');
    expect(r.content).toContain('[CITATION NEEDED]');
    expect(r.content).not.toContain('{{today}}');
  });
});

describe('ingestion simulator', () => {
  const base: LegalDocument = { ...doc(DOC.lease), status: 'processing', pages: 10, isScanned: true, stage: 'validating' };

  it('walks through the pipeline stages with OCR page progress', () => {
    const job = { startedAt: 0, failAt: null };
    expect(advance(base, job, 100).stage).toBe('validating');
    const ocr = advance(base, job, 900 + 650 * 3 + 10);
    expect(ocr.stage).toBe('ocr');
    expect(ocr.progress).toEqual({ current: 4, total: 10 });
    expect(advance(base, job, 60_000)).toMatchObject({ status: 'ready', stage: null });
  });

  it('fails a corrupt file during extraction', () => {
    const r = advance({ ...base, isScanned: false }, { startedAt: 0, failAt: 'extracting' }, 60_000);
    expect(r.status).toBe('failed');
    expect(r.error).toMatch(/corrupted/);
  });
});
