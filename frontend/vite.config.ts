import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';

/**
 * Two modes share this config:
 *  - default: the UI runs on the MSW mock backend (no Python needed).
 *  - `--mode backend` (.env.backend): MSW is off and `/api` is proxied to FastAPI.
 */
export default defineConfig(({ mode }) => {
  // '' = also read non-VITE_ variables, so VITE_API_TARGET can come from the shell.
  const env = loadEnv(mode, process.cwd(), '');
  const realBackend = env.VITE_USE_MOCKS === 'false';
  const proxy = realBackend
    ? { '/api': { target: env.VITE_API_TARGET || 'http://127.0.0.1:8000' } }
    : undefined;

  return {
    plugins: [react()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    build: {
      // Separate folders, so a mock build and a backend build never overwrite each other.
      outDir: realBackend ? 'dist-backend' : 'dist',
      // Served from localhost, so a ~650 kB main chunk is fine; the mock backend is split out.
      chunkSizeWarningLimit: 800,
    },
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: realBackend ? 4174 : 4173, strictPort: true, proxy },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      css: { modules: { classNameStrategy: 'non-scoped' } },
    },
  };
});
