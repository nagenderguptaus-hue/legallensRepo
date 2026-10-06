import type { IngestionStage, LegalDocument } from '@/api/types';

/** Server-side bookkeeping for a document that is being (re)ingested. */
export interface IngestJob {
  startedAt: number;
  failAt: IngestionStage | null;
}

const STAGE_MS: Record<Exclude<IngestionStage, 'extracting' | 'ocr'>, number> = {
  validating: 900,
  quality_check: 1000,
  chunking: 900,
  indexing: 1400,
};
const PAGE_MS = { digital: 220, ocr: 650 };

/**
 * Derives the current ingestion state purely from elapsed time, so progress is consistent
 * across reloads and every poll of GET /api/documents/{id} sees a believable pipeline:
 * validating → extracting | ocr (page n/N) → quality_check → chunking → indexing → ready.
 */
export function advance(doc: LegalDocument, job: IngestJob, now: number): LegalDocument {
  const total = doc.pages ?? 1;
  const pageStage: IngestionStage = doc.isScanned ? 'ocr' : 'extracting';
  const plan: { stage: IngestionStage; ms: number }[] = [
    { stage: 'validating', ms: STAGE_MS.validating },
    { stage: pageStage, ms: total * (doc.isScanned ? PAGE_MS.ocr : PAGE_MS.digital) },
    { stage: 'quality_check', ms: STAGE_MS.quality_check },
    { stage: 'chunking', ms: STAGE_MS.chunking },
    { stage: 'indexing', ms: STAGE_MS.indexing },
  ];

  let elapsed = now - job.startedAt;
  for (const step of plan) {
    // fail a little way into the stage so the user sees it start
    if (job.failAt === step.stage && elapsed >= step.ms * 0.4) {
      return {
        ...doc,
        status: 'failed',
        stage: null,
        progress: null,
        error: 'Could not read this file. It may be corrupted or password-protected.',
      };
    }
    if (elapsed < step.ms) {
      const progress =
        step.stage === pageStage
          ? { current: Math.min(total, Math.floor((elapsed / step.ms) * total) + 1), total }
          : null;
      return { ...doc, status: 'processing', stage: step.stage, progress, error: null };
    }
    elapsed -= step.ms;
  }

  return {
    ...doc,
    status: 'ready',
    stage: null,
    progress: null,
    error: null,
    warnings: doc.isScanned
      ? [`Low OCR confidence on page ${Math.min(2, total)}. Check citations from that page.`]
      : [],
  };
}

/** Rough page estimate for an uploaded file (the mock cannot open it). */
export function estimatePages(sizeBytes: number, type: 'pdf' | 'docx'): number {
  const perPage = type === 'pdf' ? 90_000 : 25_000;
  return Math.max(2, Math.min(40, Math.round(sizeBytes / perPage)));
}
