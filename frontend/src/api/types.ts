/**
 * API contract shared by the UI and the (mock or real) backend.
 * Mirrors the endpoints in architecture/legal_lens_flow.excalidraw.
 *
 * Additive extensions to the diagram's SSE contract (the backend should implement them):
 *  - `intent` also carries the server ids of the new user + assistant messages, so a reply that
 *    is stopped or fails midway can be reconciled with later refetches.
 *  - `status` event: human-readable progress ("Searching the document…") for slow local models.
 *  - `done` carries `outcome`, `suggestions` (for clarify) and `title` (auto-titled chats).
 *  - `POST /api/documents/{id}/retry` re-runs ingestion for a failed document.
 */

export type Intent = 'ask' | 'summary' | 'draft' | 'clarify';

export type Outcome = 'answered' | 'not_found' | 'clarify' | 'needs_document';

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id: string;
}

// ---------------------------------------------------------------- documents

export type DocumentStatus = 'processing' | 'ready' | 'failed';

export type IngestionStage =
  | 'validating'
  | 'extracting'
  | 'ocr'
  | 'quality_check'
  | 'chunking'
  | 'indexing';

export interface LegalDocument {
  id: string;
  name: string;
  type: 'pdf' | 'docx';
  sizeBytes: number;
  pages: number | null;
  status: DocumentStatus;
  stage: IngestionStage | null;
  /** Page progress for the extracting/ocr stages. */
  progress: { current: number; total: number } | null;
  isScanned: boolean;
  warnings: string[];
  error: string | null;
  uploadedAt: string;
}

export interface DocumentPage {
  documentId: string;
  page: number;
  totalPages: number;
  /** Paragraphs of extracted text. */
  paragraphs: string[];
  ocr: boolean;
  ocrConfidence: number | null;
}

// ---------------------------------------------------------------- conversations

export interface Citation {
  /** 1-based number used inline in the text as [n]. */
  index: number;
  documentId: string;
  documentName: string;
  page: number;
  section: string | null;
  quote: string;
}

export type MessageStatus = 'complete' | 'streaming' | 'stopped' | 'error';

export interface Message {
  id: string;
  conversationId: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  status: MessageStatus;
  intent: Intent | null;
  outcome: Outcome | null;
  citations: Citation[];
  suggestions: string[];
  documentId: string | null;
  /** Present when status is 'error'. */
  error?: ApiErrorBody;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  documentId: string | null;
  /** True when the document this chat used has since been deleted (FR-21). */
  documentDeleted: boolean;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

// ---------------------------------------------------------------- chat stream (SSE)

export interface ChatRequest {
  conversation_id: string;
  message: string;
  document_ids: string[];
}

export type ChatEvent =
  | { event: 'intent'; data: { intent: Intent; message_id: string; user_message_id: string } }
  | { event: 'status'; data: { label: string } }
  | { event: 'token'; data: { text: string } }
  | { event: 'citation'; data: Citation }
  | {
      event: 'done';
      data: {
        message_id: string;
        user_message_id: string;
        outcome: Outcome;
        suggestions: string[];
        title: string;
      };
    }
  | { event: 'error'; data: ApiErrorBody };

// ---------------------------------------------------------------- health

export type ModelRuntimeStatus = 'ready' | 'loading' | 'unavailable';

export interface Health {
  status: 'ok' | 'degraded';
  modelRuntime: ModelRuntimeStatus;
  model: string;
}
