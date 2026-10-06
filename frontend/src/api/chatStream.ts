import { networkError, toApiError } from './client';
import type { ChatEvent, ChatRequest } from './types';

/**
 * Incremental Server-Sent Events parser.
 * Handles events split across network chunks and multi-line `data:` fields.
 */
export class SSEParser {
  private buffer = '';

  push(chunk: string): ChatEvent[] {
    this.buffer += chunk.replace(/\r\n/g, '\n');
    const events: ChatEvent[] = [];
    let boundary = this.buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const parsed = parseBlock(block);
      if (parsed) events.push(parsed);
      boundary = this.buffer.indexOf('\n\n');
    }
    return events;
  }
}

function parseBlock(block: string): ChatEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue; // comment / keep-alive
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
  }
  if (data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join('\n')) } as ChatEvent;
  } catch {
    return null;
  }
}

/**
 * POSTs a chat message and yields SSE events as they arrive.
 * Uses fetch + ReadableStream because EventSource cannot send a POST body.
 */
export async function* streamChat(
  body: ChatRequest,
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  let res: Response;
  try {
    res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw networkError();
  }
  if (!res.ok || !res.body) throw await toApiError(res);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SSEParser();
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      yield* parser.push(value);
    }
  } finally {
    reader.releaseLock();
  }
}
