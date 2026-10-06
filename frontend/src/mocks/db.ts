/**
 * In-memory mock database, persisted to localStorage so chats and uploads survive a reload
 * (standing in for SQLite). "Reset demo data" rebuilds it from the seed.
 */
import type { Conversation, LegalDocument, Message } from '@/api/types';
import { buildSeed, type DbState } from './data/seed';
import { advance } from './engine/ingestion';

const DB_KEY = 'legallens.mockdb.v1';
const SETTINGS_KEY = 'legallens.mock.settings.v1';

export interface MockSettings {
  /** Stream ~4× slower, to rehearse the experience with a slow local model. */
  slowStream: boolean;
  /** Fail the next chat request halfway through the answer. */
  failNextMessage: boolean;
  /** Pretend the local model runtime is down (health = unavailable, chat = 503). */
  modelOffline: boolean;
}

const DEFAULT_SETTINGS: MockSettings = {
  slowStream: false,
  failNextMessage: false,
  modelOffline: false,
};

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage full or unavailable; the demo keeps working in memory
  }
}

let state: DbState = readJson<DbState>(DB_KEY) ?? buildSeed(Date.now());
let settings: MockSettings = { ...DEFAULT_SETTINGS, ...readJson<MockSettings>(SETTINGS_KEY) };

export function persist() {
  writeJson(DB_KEY, state);
}

export function resetDb() {
  state = buildSeed(Date.now());
  persist();
}

export function getSettings(): MockSettings {
  return settings;
}

export function updateSettings(patch: Partial<MockSettings>) {
  settings = { ...settings, ...patch };
  writeJson(SETTINGS_KEY, settings);
}

export function newId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

// ---------------------------------------------------------------- documents

/** Advances any in-flight ingestion jobs to "now" and returns the documents. */
export function listDocuments(): LegalDocument[] {
  const now = Date.now();
  let changed = false;
  state.documents = state.documents.map((doc) => {
    const job = state.jobs[doc.id];
    if (doc.status !== 'processing' || !job) return doc;
    const next = advance(doc, job, now);
    if (next.status !== 'processing') delete state.jobs[doc.id];
    changed = true;
    return next;
  });
  if (changed) persist();
  return [...state.documents].sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
}

export function findDocument(id: string): LegalDocument | null {
  return listDocuments().find((d) => d.id === id) ?? null;
}

export function insertDocument(doc: LegalDocument, failAt: 'extracting' | 'ocr' | null) {
  state.documents.unshift(doc);
  state.jobs[doc.id] = { startedAt: Date.now(), failAt };
  persist();
}

export function restartIngestion(id: string): LegalDocument | null {
  const doc = state.documents.find((d) => d.id === id);
  if (!doc) return null;
  Object.assign(doc, {
    status: 'processing',
    stage: 'validating',
    progress: null,
    error: null,
    pages: doc.pages ?? 8,
  } satisfies Partial<LegalDocument>);
  state.jobs[id] = { startedAt: Date.now(), failAt: null };
  persist();
  return doc;
}

export function removeDocument(id: string): boolean {
  const before = state.documents.length;
  state.documents = state.documents.filter((d) => d.id !== id);
  delete state.jobs[id];
  for (const c of state.conversations) {
    if (c.documentId === id) c.documentDeleted = true;
  }
  persist();
  return state.documents.length < before;
}

// ---------------------------------------------------------------- conversations

export function listConversations(): Conversation[] {
  return [...state.conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function findConversation(id: string): Conversation | null {
  return state.conversations.find((c) => c.id === id) ?? null;
}

export function insertConversation(conversation: Conversation) {
  state.conversations.push(conversation);
  persist();
}

export function patchConversation(id: string, patch: Partial<Conversation>): Conversation | null {
  const c = findConversation(id);
  if (!c) return null;
  Object.assign(c, patch);
  persist();
  return c;
}

export function removeConversation(id: string): boolean {
  const before = state.conversations.length;
  state.conversations = state.conversations.filter((c) => c.id !== id);
  state.messages = state.messages.filter((m) => m.conversationId !== id);
  persist();
  return state.conversations.length < before;
}

export function listMessages(conversationId: string): Message[] {
  return state.messages
    .filter((m) => m.conversationId === conversationId)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export function insertMessage(message: Message) {
  state.messages.push(message);
}
