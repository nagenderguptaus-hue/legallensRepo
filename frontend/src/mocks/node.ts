import { setupServer } from 'msw/node';
import { handlers } from './handlers';

/** MSW server for Vitest: the same handlers the browser uses. */
export const server = setupServer(...handlers);
