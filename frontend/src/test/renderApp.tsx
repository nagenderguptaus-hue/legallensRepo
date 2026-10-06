import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { AppRoutes } from '@/app/AppRoutes';
import { Providers } from '@/app/Providers';
import { createQueryClient } from '@/app/queryClient';

/** Renders the full app (real components + MSW mock backend) at a given route. */
export function renderApp(route = '/') {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  const user = userEvent.setup();
  const utils = render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
  return { user, client, ...utils };
}
