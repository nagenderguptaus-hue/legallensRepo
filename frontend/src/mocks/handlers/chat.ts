import { http, HttpResponse } from 'msw';
import type { ChatEvent, ChatRequest, Message } from '@/api/types';
import {
  findConversation,
  findDocument,
  getSettings,
  insertMessage,
  listMessages,
  newId,
  persist,
  updateSettings,
} from '../db';
import { respond, truncate } from '../engine/respond';
import { apiError, sleep } from './util';

const encoder = new TextEncoder();

function sse(evt: ChatEvent): Uint8Array {
  return encoder.encode(`event: ${evt.event}\ndata: ${JSON.stringify(evt.data)}\n\n`);
}

/** Splits text into small word groups so it streams like model tokens. */
function toTokens(text: string): string[] {
  const words = text.match(/\S+\s*/g) ?? [];
  const tokens: string[] = [];
  for (let i = 0; i < words.length; i += 2) tokens.push(words.slice(i, i + 2).join(''));
  return tokens;
}

function titleFrom(message: string): string {
  const clean = message.trim().replace(/\s+/g, ' ').replace(/[?.!]+$/, '');
  return truncate(clean.charAt(0).toUpperCase() + clean.slice(1), 48);
}

export const chatHandlers = [
  http.post('/api/chat/stream', async ({ request }) => {
    const body = (await request.json()) as ChatRequest;
    const settings = getSettings();

    if (settings.modelOffline) {
      return apiError(
        503,
        'model_unavailable',
        'The local model runtime is not responding. Start it and try again.',
      );
    }
    const conversation = findConversation(body.conversation_id);
    if (!conversation) return apiError(404, 'conversation_not_found', 'This conversation does not exist.');
    const text = body.message?.trim();
    if (!text) return apiError(422, 'empty_message', 'Message cannot be empty.');
    if (text.length > 8000) return apiError(422, 'message_too_long', 'Messages are limited to 8,000 characters.');

    const documentId = body.document_ids[0] ?? null;
    const document = documentId ? findDocument(documentId) : null;
    if (documentId && document?.status !== 'ready') {
      return apiError(409, 'document_not_ready', 'That document is not ready yet. Wait for processing to finish.');
    }

    const previousUserMessages = listMessages(conversation.id)
      .filter((m) => m.role === 'user')
      .map((m) => m.content);
    const result = respond({ message: text, document, previousUserMessages });

    const now = Date.now();
    const base = { conversationId: conversation.id, documentId, citations: [], suggestions: [] };
    const userMessage: Message = {
      ...base,
      id: newId('msg'),
      role: 'user',
      content: text,
      createdAt: new Date(now).toISOString(),
      status: 'complete',
      intent: null,
      outcome: null,
    };
    const assistant: Message = {
      ...base,
      id: newId('msg'),
      role: 'assistant',
      content: '',
      createdAt: new Date(now + 1).toISOString(),
      status: 'streaming',
      intent: result.intent,
      outcome: null,
    };
    insertMessage(userMessage);
    insertMessage(assistant);
    conversation.updatedAt = assistant.createdAt;
    if (documentId) {
      conversation.documentId = documentId;
      conversation.documentDeleted = false;
    }
    if (conversation.title === 'New conversation') conversation.title = titleFrom(text);
    persist();

    const failMidway = settings.failNextMessage;
    if (failMidway) updateSettings({ failNextMessage: false });
    const pace = settings.slowStream ? 4 : 1;
    let cancelled = false;

    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const send = (evt: ChatEvent) => {
          if (!cancelled) controller.enqueue(sse(evt));
        };
        send({
          event: 'intent',
          data: { intent: result.intent, message_id: assistant.id, user_message_id: userMessage.id },
        });
        for (const label of result.statusSteps) {
          send({ event: 'status', data: { label } });
          await sleep(420 * pace);
          if (cancelled) return;
        }

        const tokens = toTokens(result.content);
        for (const [i, token] of tokens.entries()) {
          if (cancelled) return;
          if (failMidway && i === Math.floor(tokens.length / 2)) {
            const error = {
              code: 'stream_interrupted',
              message: 'The model stopped responding partway through the answer.',
              request_id: newId('req'),
            };
            assistant.status = 'error';
            assistant.error = error;
            persist();
            send({ event: 'error', data: error });
            controller.close();
            return;
          }
          assistant.content += token;
          send({ event: 'token', data: { text: token } });
          await sleep(24 * pace);
        }

        for (const citation of result.citations) send({ event: 'citation', data: citation });
        Object.assign(assistant, {
          status: 'complete',
          outcome: result.outcome,
          citations: result.citations,
          suggestions: result.suggestions,
        } satisfies Partial<Message>);
        persist();
        send({
          event: 'done',
          data: {
            message_id: assistant.id,
            user_message_id: userMessage.id,
            outcome: result.outcome,
            suggestions: result.suggestions,
            title: conversation.title,
          },
        });
        if (!cancelled) controller.close();
      },
      cancel() {
        // The client pressed Stop (or navigated away): keep what was generated so far.
        cancelled = true;
        if (assistant.status === 'streaming') {
          assistant.status = 'stopped';
          persist();
        }
      },
    });

    return new HttpResponse(stream, {
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    });
  }),
];
