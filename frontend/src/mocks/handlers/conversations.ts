import { http, HttpResponse } from 'msw';
import type { Conversation } from '@/api/types';
import {
  findConversation,
  insertConversation,
  listConversations,
  listMessages,
  newId,
  patchConversation,
  removeConversation,
} from '../db';
import { apiError, latency } from './util';

export const conversationHandlers = [
  http.get('/api/conversations', async () => {
    await latency();
    return HttpResponse.json(listConversations());
  }),

  http.post('/api/conversations', async ({ request }) => {
    await latency(80, 160);
    const body = (await request.json()) as { title?: string; documentId?: string | null };
    const now = new Date().toISOString();
    const conversation: Conversation = {
      id: newId('conv'),
      title: body.title?.trim() || 'New conversation',
      documentId: body.documentId ?? null,
      documentDeleted: false,
      createdAt: now,
      updatedAt: now,
    };
    insertConversation(conversation);
    return HttpResponse.json(conversation, { status: 201 });
  }),

  http.get('/api/conversations/:id', async ({ params }) => {
    await latency();
    const conversation = findConversation(String(params.id));
    if (!conversation) return apiError(404, 'conversation_not_found', 'This conversation does not exist.');
    return HttpResponse.json({ ...conversation, messages: listMessages(conversation.id) });
  }),

  http.patch('/api/conversations/:id', async ({ params, request }) => {
    await latency(80, 200);
    const patch = (await request.json()) as { title?: string; documentId?: string | null };
    if (patch.title !== undefined && !patch.title.trim()) {
      return apiError(422, 'invalid_title', 'Title cannot be empty.');
    }
    const updated = patchConversation(String(params.id), {
      ...(patch.title !== undefined && { title: patch.title.trim().slice(0, 120) }),
      ...(patch.documentId !== undefined && { documentId: patch.documentId, documentDeleted: false }),
    });
    if (!updated) return apiError(404, 'conversation_not_found', 'This conversation does not exist.');
    return HttpResponse.json(updated);
  }),

  http.delete('/api/conversations/:id', async ({ params }) => {
    await latency(80, 200);
    if (!removeConversation(String(params.id))) {
      return apiError(404, 'conversation_not_found', 'This conversation does not exist.');
    }
    return new HttpResponse(null, { status: 204 });
  }),
];
