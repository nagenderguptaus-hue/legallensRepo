import '@testing-library/jest-dom/vitest';
import { File as NodeFile } from 'node:buffer';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';
import { resetDb, updateSettings } from '@/mocks/db';
import { server } from '@/mocks/node';
import { useChatStore } from '@/store/chatStore';
import { useUiStore } from '@/store/uiStore';

// ---- jsdom gaps used by Radix UI and our components
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= function scrollIntoView() {};
Element.prototype.scrollTo ??= function scrollTo() {};
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia;

beforeAll(async () => {
  // jsdom's File/FormData can't be sent through Node's fetch; use Node's native ones instead.
  // (Response is Node's here, so it hands us Node's FormData constructor.)
  const NodeFormData = (
    await new Response('', { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }).formData()
  ).constructor as typeof FormData;
  globalThis.FormData = NodeFormData;
  globalThis.File = NodeFile as unknown as typeof File;

  server.listen({ onUnhandledRequest: 'error' });
  // Node's fetch can't resolve relative URLs; resolve them against the jsdom origin.
  const mswFetch = globalThis.fetch;
  globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
    mswFetch(typeof input === 'string' && input.startsWith('/') ? new URL(input, window.location.origin) : input, init);
});

beforeEach(() => {
  localStorage.clear();
  useUiStore.setState(useUiStore.getInitialState(), true);
  useChatStore.setState(useChatStore.getInitialState(), true);
  resetDb();
  updateSettings({ slowStream: false, failNextMessage: false, modelOffline: false });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => server.close());
