import { HttpResponse } from 'msw';
import { newId } from '../db';

/** Error response in the backend's standard envelope. */
export function apiError(status: number, code: string, message: string) {
  return HttpResponse.json({ code, message, request_id: newId('req') }, { status });
}

/** No artificial waits under Vitest; realistic pacing in the browser. */
export const TIME_SCALE = import.meta.env.MODE === 'test' ? 0 : 1;

export function sleep(ms: number): Promise<void> {
  const scaled = ms * TIME_SCALE;
  return scaled <= 0 ? Promise.resolve() : new Promise((r) => setTimeout(r, scaled));
}

/** Simulated network latency for REST calls. */
export function latency(min = 120, max = 320) {
  return sleep(min + Math.random() * (max - min));
}
