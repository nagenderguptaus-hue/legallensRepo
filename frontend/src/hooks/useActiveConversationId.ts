import { useMatch } from 'react-router';

/** The conversation id in the URL, usable from layout-level components (sidebar, panel). */
export function useActiveConversationId(): string | undefined {
  return useMatch('/c/:conversationId')?.params.conversationId;
}
