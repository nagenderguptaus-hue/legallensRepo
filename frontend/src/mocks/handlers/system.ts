import { http, HttpResponse } from 'msw';
import type { Health } from '@/api/types';
import { getSettings, resetDb, updateSettings, type MockSettings } from '../db';
import { latency } from './util';

export const systemHandlers = [
  http.get('/api/health', async () => {
    await latency(40, 100);
    const offline = getSettings().modelOffline;
    const health: Health = {
      status: offline ? 'degraded' : 'ok',
      modelRuntime: offline ? 'unavailable' : 'ready',
      model: 'Local LLM · 8B instruct (mock)',
    };
    return HttpResponse.json(health);
  }),

  // ---- mock-only controls (used by the dev panel; not part of the real API)
  http.get('/api/__mock/settings', () => HttpResponse.json(getSettings())),

  http.patch('/api/__mock/settings', async ({ request }) => {
    updateSettings((await request.json()) as Partial<MockSettings>);
    return HttpResponse.json(getSettings());
  }),

  http.post('/api/__mock/reset', () => {
    resetDb();
    return new HttpResponse(null, { status: 204 });
  }),
];
