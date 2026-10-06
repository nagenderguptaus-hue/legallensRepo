import type { ConversationDetail, LegalDocument } from '@/api/types';
import { useDocuments, useUpdateConversation } from '@/hooks/queries';
import { useUiStore } from '@/store/uiStore';

/**
 * Which document the composer answers from.
 * - Existing conversation: the conversation's document (persisted via PATCH).
 * - New chat: the user's choice, or automatically the most recent Ready document.
 */
export function useDocumentContext(conversation: ConversationDetail | undefined) {
  const documents = useDocuments().data ?? [];
  const ready = documents.filter((d) => d.status === 'ready');
  const choice = useUiStore((s) => s.newChatDocument);
  const setNewChatDocument = useUiStore((s) => s.setNewChatDocument);
  const update = useUpdateConversation();

  let documentId: string | null;
  if (conversation) {
    documentId = conversation.documentDeleted ? null : conversation.documentId;
  } else if (choice === null) {
    documentId = null;
  } else {
    documentId = ready.some((d) => d.id === choice) ? (choice as string) : (ready[0]?.id ?? null);
  }

  const document: LegalDocument | null = documents.find((d) => d.id === documentId) ?? null;

  const setDocumentId = (id: string | null) => {
    if (conversation) update.mutate({ id: conversation.id, documentId: id });
    else setNewChatDocument(id);
  };

  return { documentId, document, documents, setDocumentId };
}
