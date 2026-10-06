import { describe, expect, it } from 'vitest';
import { SSEParser } from './chatStream';

describe('SSEParser', () => {
  it('parses complete events', () => {
    const p = new SSEParser();
    const events = p.push('event: token\ndata: {"text":"Hello"}\n\nevent: token\ndata: {"text":" world"}\n\n');
    expect(events).toEqual([
      { event: 'token', data: { text: 'Hello' } },
      { event: 'token', data: { text: ' world' } },
    ]);
  });

  it('buffers events split across network chunks', () => {
    const p = new SSEParser();
    expect(p.push('event: intent\nda')).toEqual([]);
    expect(p.push('ta: {"intent":"ask","message_id":"m","user_message_id":"u"}\n')).toEqual([]);
    expect(p.push('\n')).toEqual([
      { event: 'intent', data: { intent: 'ask', message_id: 'm', user_message_id: 'u' } },
    ]);
  });

  it('handles CRLF line endings, comments and multi-line data', () => {
    const p = new SSEParser();
    const events = p.push(': keep-alive\r\n\r\nevent: status\r\ndata: {"label":\r\ndata: "Searching"}\r\n\r\n');
    expect(events).toEqual([{ event: 'status', data: { label: 'Searching' } }]);
  });

  it('skips malformed JSON instead of throwing', () => {
    const p = new SSEParser();
    expect(p.push('event: token\ndata: {not json}\n\n')).toEqual([]);
  });
});
