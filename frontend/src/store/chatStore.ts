import { create } from 'zustand';
import type { Message } from '@/api/types';

/** A turn that is still streaming (not yet merged into the conversation query cache). */
export interface PendingTurn {
  user: Message;
  assistant: Message;
  statusLabel: string | null;
  controller: AbortController;
}

interface ChatState {
  pending: Record<string, PendingTurn>;
  start: (conversationId: string, turn: PendingTurn) => void;
  update: (conversationId: string, fn: (turn: PendingTurn) => PendingTurn) => void;
  clear: (conversationId: string) => void;
}

export const useChatStore = create<ChatState>()((set) => ({
  pending: {},
  start: (conversationId, turn) => set((s) => ({ pending: { ...s.pending, [conversationId]: turn } })),
  update: (conversationId, fn) =>
    set((s) => {
      const turn = s.pending[conversationId];
      return turn ? { pending: { ...s.pending, [conversationId]: fn(turn) } } : s;
    }),
  clear: (conversationId) =>
    set((s) => {
      const pending = { ...s.pending };
      delete pending[conversationId];
      return { pending };
    }),
}));

export function usePendingTurn(conversationId: string | undefined): PendingTurn | undefined {
  return useChatStore((s) => (conversationId ? s.pending[conversationId] : undefined));
}

export function useIsStreaming(conversationId: string | undefined): boolean {
  return useChatStore((s) => Boolean(conversationId && s.pending[conversationId]));
}
