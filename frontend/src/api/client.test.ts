import { describe, expect, it } from 'vitest';
import { isServiceUnreachable, toApiError } from './client';

const envelope = (code: string, status: number) =>
  new Response(JSON.stringify({ code, message: 'Readable message', request_id: 'req_1' }), { status });

describe('toApiError', () => {
  it('keeps the backend error envelope', async () => {
    const err = await toApiError(envelope('model_unavailable', 503));
    expect(err).toMatchObject({ code: 'model_unavailable', message: 'Readable message', requestId: 'req_1', status: 503 });
    expect(isServiceUnreachable(err)).toBe(false);
  });

  it.each([502, 503, 504])('treats a bare %i from the proxy as the backend being down', async (status) => {
    const err = await toApiError(new Response('Bad gateway', { status }));
    expect(err.code).toBe('network_error');
    expect(isServiceUnreachable(err)).toBe(true);
  });

  it('hides other non-envelope errors behind a generic message', async () => {
    const err = await toApiError(new Response('<html>oops</html>', { status: 500 }));
    expect(err.code).toBe('http_error');
    expect(err.message).not.toContain('oops');
  });
});
