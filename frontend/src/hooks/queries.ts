import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ApiError } from '@/api/client';
import { conversationsApi } from '@/api/conversations';
import { documentsApi, healthApi } from '@/api/documents';
import type { Conversation, ConversationDetail, LegalDocument } from '@/api/types';

export const keys = {
  conversations: ['conversations'] as const,
  conversation: (id: string) => ['conversation', id] as const,
  documents: ['documents'] as const,
  page: (documentId: string, page: number) => ['document-page', documentId, page] as const,
  health: ['health'] as const,
};

export function errorToast(title: string, err: unknown) {
  const description =
    err instanceof ApiError
      ? `${err.message}${err.requestId !== 'none' && err.requestId !== 'unknown' ? ` (ref ${err.requestId})` : ''}`
      : 'Something went wrong. Please try again.';
  toast.error(title, { description });
}

// ---------------------------------------------------------------- conversations

export function useConversations() {
  return useQuery({ queryKey: keys.conversations, queryFn: conversationsApi.list });
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: keys.conversation(id ?? ''),
    queryFn: () => conversationsApi.get(id!),
    enabled: Boolean(id),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
}

export function useUpdateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: string; title?: string; documentId?: string | null }) =>
      conversationsApi.update(id, patch),
    onMutate: async ({ id, ...patch }) => {
      await qc.cancelQueries({ queryKey: keys.conversations });
      const previous = qc.getQueryData<Conversation[]>(keys.conversations);
      qc.setQueryData<Conversation[]>(keys.conversations, (list) =>
        list?.map((c) => (c.id === id ? { ...c, ...patch } : c)),
      );
      qc.setQueryData<ConversationDetail>(keys.conversation(id), (c) => (c ? { ...c, ...patch } : c));
      return { previous };
    },
    onError: (err, { id }, ctx) => {
      qc.setQueryData(keys.conversations, ctx?.previous);
      void qc.invalidateQueries({ queryKey: keys.conversation(id) });
      errorToast('Could not update the conversation', err);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: keys.conversations }),
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => conversationsApi.remove(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: keys.conversations });
      const previous = qc.getQueryData<Conversation[]>(keys.conversations);
      qc.setQueryData<Conversation[]>(keys.conversations, (list) => list?.filter((c) => c.id !== id));
      return { previous };
    },
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: keys.conversation(id) });
      toast.success('Conversation deleted');
    },
    onError: (err, _id, ctx) => {
      qc.setQueryData(keys.conversations, ctx?.previous);
      errorToast('Could not delete the conversation', err);
    },
  });
}

// ---------------------------------------------------------------- documents

export function useDocuments() {
  return useQuery({
    queryKey: keys.documents,
    queryFn: documentsApi.list,
    // Poll while anything is being ingested, so progress updates live.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === 'processing') ? 1000 : false,
  });
}

export function useReadyDocuments(): LegalDocument[] {
  return useDocuments().data?.filter((d) => d.status === 'ready') ?? [];
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => documentsApi.upload(file),
    onSuccess: (doc) => {
      qc.setQueryData<LegalDocument[]>(keys.documents, (list) => [doc, ...(list ?? [])]);
      void qc.invalidateQueries({ queryKey: keys.documents });
    },
    onError: (err, file) => errorToast(`Couldn’t upload “${file.name}”`, err),
  });
}

export function useRetryDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => documentsApi.retry(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents }),
    onError: (err) => errorToast('Could not retry processing', err),
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (doc: LegalDocument) => documentsApi.remove(doc.id),
    onSuccess: (_, doc) => {
      qc.setQueryData<LegalDocument[]>(keys.documents, (list) => list?.filter((d) => d.id !== doc.id));
      // Conversations that used it are now marked "source deleted" server-side.
      void qc.invalidateQueries({ queryKey: ['conversation'] });
      void qc.invalidateQueries({ queryKey: keys.conversations });
      toast.success(`Deleted “${doc.name}”`, {
        description: 'The file, its extracted text and its search index were removed.',
      });
    },
    onError: (err) => errorToast('Could not delete the document', err),
  });
}

export function useDocumentPage(documentId: string | undefined, page: number) {
  return useQuery({
    queryKey: keys.page(documentId ?? '', page),
    queryFn: () => documentsApi.page(documentId!, page),
    enabled: Boolean(documentId),
    retry: false,
  });
}

// ---------------------------------------------------------------- health

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: healthApi.get,
    refetchInterval: (query) => (query.state.data?.modelRuntime === 'ready' ? 15_000 : 4_000),
    retry: false,
  });
}
