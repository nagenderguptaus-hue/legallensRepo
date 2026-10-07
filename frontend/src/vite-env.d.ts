/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'false' = call the real backend; anything else = MSW mocks. */
  readonly VITE_USE_MOCKS?: string;
  /** Dev/preview proxy target for /api (read by vite.config.ts, not by app code). */
  readonly VITE_API_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
