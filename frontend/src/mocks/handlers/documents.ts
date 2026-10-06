import { http, HttpResponse } from 'msw';
import type { DocumentPage, LegalDocument } from '@/api/types';
import { MAX_UPLOAD_BYTES } from '@/lib/files';
import { OCR_LOW_CONFIDENCE_PAGES, seededPage, simulatedPage } from '../data/documents';
import { findDocument, insertDocument, listDocuments, newId, removeDocument, restartIngestion } from '../db';
import { estimatePages } from '../engine/ingestion';
import { apiError, latency } from './util';

export const documentHandlers = [
  http.get('/api/documents', async () => {
    await latency(80, 200);
    return HttpResponse.json(listDocuments());
  }),

  http.post('/api/documents', async ({ request }) => {
    await latency(400, 900); // upload time
    const form = await request.formData();
    const file = form.get('file');
    if (!(file instanceof File)) return apiError(400, 'missing_file', 'No file was uploaded.');

    const ext = file.name.split('.').pop()?.toLowerCase();
    if (ext !== 'pdf' && ext !== 'docx') {
      return apiError(415, 'unsupported_type', 'Only PDF and Word (.docx) files are supported.');
    }
    if (file.size === 0) return apiError(422, 'empty_file', 'This file is empty.');
    if (file.size > MAX_UPLOAD_BYTES) {
      return apiError(413, 'file_too_large', 'Files must be 25 MB or smaller.');
    }
    if (listDocuments().some((d) => d.name === file.name && d.sizeBytes === file.size)) {
      return apiError(409, 'duplicate_document', 'This file is already in your library.');
    }

    const isScanned = /scan/i.test(file.name);
    const doc: LegalDocument = {
      id: newId('doc'),
      name: file.name,
      type: ext,
      sizeBytes: file.size,
      pages: estimatePages(file.size, ext),
      status: 'processing',
      stage: 'validating',
      progress: null,
      isScanned,
      warnings: [],
      error: null,
      uploadedAt: new Date().toISOString(),
    };
    const failAt = /corrupt|broken/i.test(file.name) ? (isScanned ? 'ocr' : 'extracting') : null;
    insertDocument(doc, failAt);
    return HttpResponse.json(doc, { status: 201 });
  }),

  http.get('/api/documents/:id', async ({ params }) => {
    await latency(60, 140);
    const doc = findDocument(String(params.id));
    if (!doc) return apiError(404, 'document_not_found', 'This document does not exist.');
    return HttpResponse.json(doc);
  }),

  http.post('/api/documents/:id/retry', async ({ params }) => {
    await latency();
    const doc = restartIngestion(String(params.id));
    if (!doc) return apiError(404, 'document_not_found', 'This document does not exist.');
    return HttpResponse.json(doc);
  }),

  http.get('/api/documents/:id/pages/:page', async ({ params }) => {
    await latency(150, 350);
    const doc = findDocument(String(params.id));
    if (!doc) return apiError(404, 'document_not_found', 'This document has been deleted.');
    const page = Number(params.page);
    const total = doc.pages ?? 1;
    if (!Number.isInteger(page) || page < 1 || page > total) {
      return apiError(404, 'page_not_found', `Page ${params.page} does not exist.`);
    }
    const lowConfidence = OCR_LOW_CONFIDENCE_PAGES[doc.id]?.includes(page) ?? false;
    const body: DocumentPage = {
      documentId: doc.id,
      page,
      totalPages: total,
      paragraphs: seededPage(doc.id, page) ?? simulatedPage(doc.name, page),
      ocr: doc.isScanned,
      ocrConfidence: doc.isScanned ? (lowConfidence ? 0.71 : 0.94) : null,
    };
    return HttpResponse.json(body);
  }),

  http.delete('/api/documents/:id', async ({ params }) => {
    await latency(150, 300);
    if (!removeDocument(String(params.id))) {
      return apiError(404, 'document_not_found', 'This document does not exist.');
    }
    return new HttpResponse(null, { status: 204 });
  }),
];
