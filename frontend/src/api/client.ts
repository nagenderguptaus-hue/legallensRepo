import type { ApiErrorBody } from './types';

/** Error thrown for any non-2xx response; carries the backend's error envelope. */
export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string;
  readonly status: number;

  constructor(body: ApiErrorBody, status: number) {
    super(body.message);
    this.name = 'ApiError';
    this.code = body.code;
    this.requestId = body.request_id;
    this.status = status;
  }
}

const GENERIC_MESSAGE = 'The Legal Lens service hit an unexpected problem. Please try again.';

/** What a proxy (Vite in dev, nginx in Docker) answers when the backend behind it is down. */
const GATEWAY_STATUSES = new Set([502, 503, 504]);

export async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as Partial<ApiErrorBody>;
    // Only trust messages that come in our error envelope; never surface raw internals.
    if (body.code && body.message) {
      return new ApiError(
        { code: body.code, message: body.message, request_id: body.request_id ?? 'unknown' },
        res.status,
      );
    }
  } catch {
    // not JSON
  }
  if (GATEWAY_STATUSES.has(res.status)) return networkError();
  return new ApiError({ code: 'http_error', message: GENERIC_MESSAGE, request_id: 'unknown' }, res.status);
}

export function networkError(): ApiError {
  return new ApiError(
    {
      code: 'network_error',
      message: 'Could not reach the Legal Lens service. Is the backend running?',
      request_id: 'none',
    },
    0,
  );
}

/** True when the backend could not be reached at all (as opposed to answering with an error). */
export function isServiceUnreachable(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'network_error';
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw networkError();
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
