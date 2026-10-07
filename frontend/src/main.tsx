import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './app/App';
import './styles/globals.css';

async function prepareApi() {
  // Same test as lib/env's USE_MOCKS, inlined so the build drops the mock chunk in backend mode.
  if (import.meta.env.VITE_USE_MOCKS !== 'false') {
    const { worker } = await import('./mocks/browser');
    await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
    return;
  }
  // A mock session on this origin leaves the MSW worker registered. It would pass requests
  // through, but remove it anyway so the mocks can never answer for the real backend.
  try {
    const registrations = (await navigator.serviceWorker?.getRegistrations()) ?? [];
    await Promise.all(
      registrations
        .filter((r) => r.active?.scriptURL.endsWith('/mockServiceWorker.js'))
        .map((r) => r.unregister()),
    );
  } catch {
    // Service workers unavailable (e.g. private mode): nothing to clean up.
  }
}

void prepareApi().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
