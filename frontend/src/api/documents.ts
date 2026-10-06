import { request } from './client';
import type { DocumentPage, Health, LegalDocument } from './types';

export const documentsApi = {
  list: () => request<LegalDocument[]>('/api/documents'),

  get: (id: string) => request<LegalDocument>(`/api/documents/${id}`),

  upload: (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<LegalDocument>('/api/documents', { method: 'POST', body });
  },

  retry: (id: string) => request<LegalDocument>(`/api/documents/${id}/retry`, { method: 'POST' }),

  page: (id: string, page: number) =>
    request<DocumentPage>(`/api/documents/${id}/pages/${page}`),

  remove: (id: string) => request<void>(`/api/documents/${id}`, { method: 'DELETE' }),
};

export const healthApi = {
  get: () => request<Health>('/api/health'),
};
