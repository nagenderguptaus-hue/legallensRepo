import { request } from './client';
import type { Conversation, ConversationDetail } from './types';

export const conversationsApi = {
  list: () => request<Conversation[]>('/api/conversations'),

  get: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),

  create: (input: { title?: string; documentId?: string | null }) =>
    request<Conversation>('/api/conversations', { method: 'POST', body: JSON.stringify(input) }),

  update: (id: string, patch: { title?: string; documentId?: string | null }) =>
    request<Conversation>(`/api/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  remove: (id: string) => request<void>(`/api/conversations/${id}`, { method: 'DELETE' }),
};
