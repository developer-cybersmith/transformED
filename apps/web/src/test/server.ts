import { setupServer } from 'msw/node';
import { handlers } from './handlers';

/**
 * One MSW server for the whole suite, started in `src/test/setup.ts`.
 *
 * Import this in a test that needs a per-test override:
 *   `server.use(http.get(url, () => HttpResponse.json(..., { status: 500 })))`
 * `setup.ts` calls `server.resetHandlers()` after every test, so an override
 * never leaks into the next one.
 */
export const server = setupServer(...handlers);
