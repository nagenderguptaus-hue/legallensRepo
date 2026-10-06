import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { useNavigate } from 'react-router';
import { ApiError } from '@/api/client';
import { streamChat } from '@/api/chatStream';
import { conversationsApi } from '@/api/conversations';
import type { ConversationDetail, Message } from '@/api/types';
import { errorToast, keys } from '@/hooks/queries';
import { useChatStore } from '@/store/chatStore';
import { useUiStore } from '@/store/uiStore';

interface SendInput {
  conversationId: string | undefined;
  text: string;
  documentId: string | null;
}

export interface SendResult {
  ok: boolean;
  /** The conversation the message went to (new chats get one created). */
  conversationId: string | undefined;
}

/** Sends a message: creates the conversation if needed, then streams the reply. */
export function useSendMessage() {
  const qc = useQueryClient();
  const navigate = useNavigate();

  return useCallback(
    async ({ conversationId, text, documentId }: SendInput): Promise<SendResult> => {
      let id = conversationId;
      if (!id) {
        try {
          const conversation = await conversationsApi.create({ documentId });
          qc.setQueryData<ConversationDetail>(keys.conversation(conversation.id), {
            ...conversation,
            messages: [],
          });
          void qc.invalidateQueries({ queryKey: keys.conversations });
          id = conversation.id;
        } catch (err) {
          errorToast('Could not start a new conversation', err);
          return { ok: false, conversationId: undefined };
        }
        const started = runChatStream(qc, id, text, documentId);
        navigate(`/c/${id}`);
        return { ok: await started, conversationId: id };
      }
      return { ok: await runChatStream(qc, id, text, documentId), conversationId: id };
    },
    [qc, navigate],
  );
}

function localMessage(
  conversationId: string,
  role: Message['role'],
  content: string,
  documentId: string | null,
): Message {
  return {
    id: `local_${role}_${Date.now()}`,
    conversationId,
    role,
    content,
    createdAt: new Date().toISOString(),
    status: role === 'user' ? 'complete' : 'streaming',
    intent: null,
    outcome: null,
    citations: [],
    suggestions: [],
    documentId,
  };
}

/**
 * Drives one SSE exchange. Returns false if the message could not be sent at all
 * (so the composer can restore the text), true otherwise.
 */
async function runChatStream(
  qc: QueryClient,
  conversationId: string,
  text: string,
  documentId: string | null,
): Promise<boolean> {
  const store = useChatStore.getState();
  const { announce } = useUiStore.getState();
  const controller = new AbortController();
  store.start(conversationId, {
    user: localMessage(conversationId, 'user', text, documentId),
    assistant: localMessage(conversationId, 'assistant', '', documentId),
    statusLabel: null,
    controller,
  });
  const update = (fn: Parameters<typeof store.update>[1]) => useChatStore.getState().update(conversationId, fn);
  let receivedAny = false;

  /** Moves the pending turn into the conversation cache (deduped by id) and clears it. */
  const commit = (patch: Partial<Message>, title?: string) => {
    const turn = useChatStore.getState().pending[conversationId];
    if (!turn) return;
    const assistant = { ...turn.assistant, ...patch };
    qc.setQueryData<ConversationDetail>(keys.conversation(conversationId), (old) => {
      if (!old) return old;
      const messages = old.messages.filter((m) => m.id !== turn.user.id && m.id !== assistant.id);
      return { ...old, ...(title && { title }), messages: [...messages, turn.user, assistant] };
    });
    useChatStore.getState().clear(conversationId);
    void qc.invalidateQueries({ queryKey: keys.conversations });
  };

  try {
    const body = { conversation_id: conversationId, message: text, document_ids: documentId ? [documentId] : [] };
    for await (const evt of streamChat(body, controller.signal)) {
      receivedAny = true;
      switch (evt.event) {
        case 'intent':
          update((t) => ({
            ...t,
            user: { ...t.user, id: evt.data.user_message_id },
            assistant: { ...t.assistant, id: evt.data.message_id, intent: evt.data.intent },
          }));
          break;
        case 'status':
          update((t) => ({ ...t, statusLabel: evt.data.label }));
          break;
        case 'token':
          update((t) => ({
            ...t,
            statusLabel: null,
            assistant: { ...t.assistant, content: t.assistant.content + evt.data.text },
          }));
          break;
        case 'citation':
          update((t) => ({
            ...t,
            assistant: { ...t.assistant, citations: [...t.assistant.citations, evt.data] },
          }));
          break;
        case 'done':
          commit(
            { status: 'complete', outcome: evt.data.outcome, suggestions: evt.data.suggestions },
            evt.data.title,
          );
          announce('Response complete.');
          return true;
        case 'error':
          commit({ status: 'error', error: evt.data });
          announce(`Response failed: ${evt.data.message}`);
          return true;
      }
    }
    // Stream ended without `done` (connection dropped).
    commit({
      status: 'error',
      error: { code: 'stream_closed', message: 'The connection closed before the answer finished.', request_id: 'none' },
    });
    return true;
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      commit({ status: 'stopped' });
      announce('Response stopped.');
      return true;
    }
    if (!receivedAny) {
      // Nothing was persisted server-side: drop the pending turn and let the caller restore the text.
      useChatStore.getState().clear(conversationId);
      errorToast('Message not sent', err);
      return false;
    }
    const apiErr = err instanceof ApiError ? err : null;
    commit({
      status: 'error',
      error: {
        code: apiErr?.code ?? 'stream_failed',
        message: apiErr?.message ?? 'The answer was interrupted.',
        request_id: apiErr?.requestId ?? 'none',
      },
    });
    return true;
  }
}
