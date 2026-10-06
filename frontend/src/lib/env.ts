/** True when the UI is served by the MSW mock backend (the default until FastAPI exists). */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== 'false';
