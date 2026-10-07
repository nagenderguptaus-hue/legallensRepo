import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { ConversationDetail } from '@/api/types';
import { updateSettings } from '@/mocks/db';
import { server } from '@/mocks/node';
import { renderApp } from '@/test/renderApp';

async function waitForDocumentContext() {
  // The composer picks the latest Ready document once the library loads.
  await screen.findByRole('button', { name: /^Document: Commercial_Lease_Agreement\.pdf/ });
}

describe('chat', () => {
  it('sends a question, streams the answer and renders citations', async () => {
    const { user } = renderApp('/');
    await waitForDocumentContext();

    await user.type(screen.getByLabelText('Message Legal Lens'), 'Can the tenant terminate the lease early?{Enter}');

    expect(await screen.findByText(/early termination option/i)).toBeInTheDocument();
    const chips = await screen.findAllByRole('button', { name: /^Source 1: Commercial_Lease_Agreement\.pdf, page 18/ });
    expect(chips.length).toBeGreaterThan(0);
    expect(screen.getAllByText('Sources').length).toBeGreaterThan(0);
    // New chats are auto-titled from the first question.
    expect(await screen.findByRole('heading', { level: 1, name: 'Can the tenant terminate the lease early' })).toBeInTheDocument();
    // The composer is cleared after sending.
    expect(screen.getByLabelText('Message Legal Lens')).toHaveValue('');
  });

  it('opens the cited passage in the source viewer', async () => {
    const { user } = renderApp('/c/conv_lease_exit');
    const [chip] = await screen.findAllByRole('button', { name: /^Source 1: Commercial_Lease_Agreement\.pdf, page 18/ });
    await user.click(chip!);

    const page = await screen.findByRole('article', { name: 'Page 18 of Commercial_Lease_Agreement.pdf' });
    const mark = await within(page).findByText(/Tenant may terminate this Lease effective/);
    expect(mark.tagName).toBe('MARK');
  });

  it('says so instead of guessing when the answer is not in the document', async () => {
    const { user } = renderApp('/');
    await waitForDocumentContext();
    await user.type(screen.getByLabelText('Message Legal Lens'), 'Does the lease include a non-compete clause?{Enter}');
    expect(await screen.findByText('Not found in the document')).toBeInTheDocument();
  });

  it('shows clarify suggestions that send a follow-up when clicked', async () => {
    const { user } = renderApp('/c/conv_clarify');
    const suggestion = await screen.findByRole('button', { name: 'Draft a memo based on this document' });
    await user.click(suggestion);
    expect(await screen.findByRole('article', { name: /Draft legal memo/i })).toBeInTheDocument();
  });

  it('blocks sending and explains why when the local model is offline', async () => {
    updateSettings({ modelOffline: true });
    renderApp('/');
    expect(await screen.findByText('The local model is unavailable.')).toBeInTheDocument();
    expect(screen.getByLabelText('Message Legal Lens')).toBeDisabled();
  });
});

describe('sidebar', () => {
  it('groups conversations by date and filters by search', async () => {
    const { user } = renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Smith v. Jones: summary' })).toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'nda');
    expect(screen.queryByRole('link', { name: 'Smith v. Jones: summary' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Memo: NDA risk review' })).toBeInTheDocument();

    await user.clear(screen.getByRole('searchbox', { name: 'Search conversations' }));
    await user.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'zzz');
    expect(screen.getByText(/No conversations match/)).toBeInTheDocument();
  });

  it('renames a conversation inline', async () => {
    const { user } = renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Options for “Getting started”' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    const input = await screen.findByRole('textbox', { name: 'Conversation title' });
    await user.clear(input);
    await user.type(input, 'Onboarding questions{Enter}');
    expect(await screen.findByRole('link', { name: 'Onboarding questions' })).toBeInTheDocument();
  });

  it('deletes a conversation after confirmation', async () => {
    const { user } = renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Options for “Getting started”' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete conversation?' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete conversation' }));
    await waitFor(() => expect(screen.queryByRole('link', { name: 'Getting started' })).not.toBeInTheDocument());
  });
});

describe('documents', () => {
  // The file input is hidden (opened via requestUpload), so dispatch its change event directly.
  const pickFiles = (files: File[]) => {
    const input = document.querySelector<HTMLInputElement>('input[type=file]')!;
    fireEvent.change(input, { target: { files } });
  };

  it('uploads a document and shows it processing', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: /Your documents/ });
    pickFiles([new File(['%PDF-1.7 demo'], 'Supply_Agreement.pdf', { type: 'application/pdf' })]);

    expect(await screen.findByText('Supply_Agreement.pdf')).toBeInTheDocument();
    expect(await screen.findByRole('progressbar', { name: 'Processing Supply_Agreement.pdf' })).toBeInTheDocument();
  });

  it('rejects unsupported files before uploading', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: /Your documents/ });
    pickFiles([new File(['hello'], 'notes.txt', { type: 'text/plain' })]);
    expect(await screen.findByText(/isn’t a PDF or Word/)).toBeInTheDocument();
    expect(screen.queryByText('notes.txt')).not.toBeInTheDocument();
  });

  it('marks a conversation when its source document is deleted', async () => {
    renderApp('/c/conv_employment');
    expect(await screen.findByText('Source document deleted')).toBeInTheDocument();
  });
});

describe('real backend conditions', () => {
  const badGateway = () => new HttpResponse('Bad gateway', { status: 502 });

  it('says the service is down (not the model) and recovers when it comes back', async () => {
    server.use(http.get('/api/health', badGateway), http.get('/api/documents', badGateway));
    const { user } = renderApp('/');
    expect(await screen.findByText('Can’t reach the Legal Lens service.')).toBeInTheDocument();
    expect(screen.getByText('Service not reachable')).toBeInTheDocument();
    expect(screen.queryByText(/documents and conversations are still available/)).not.toBeInTheDocument();

    // The backend starts: the next health check succeeds and the failed library reloads.
    server.resetHandlers();
    await user.click(screen.getByRole('button', { name: 'Check again' }));
    await waitFor(() => expect(screen.queryByText('Can’t reach the Legal Lens service.')).not.toBeInTheDocument());
    expect((await screen.findAllByText('Commercial_Lease_Agreement.pdf')).length).toBeGreaterThan(0);
  });

  it('shows a reply still generating on the server and polls until it is done', async () => {
    const stillStreaming: ConversationDetail = {
      id: 'conv_lease_exit',
      title: 'Lease: early termination rights',
      createdAt: '2026-10-06T10:00:00.000Z',
      updatedAt: '2026-10-06T10:00:00.000Z',
      documentId: null,
      documentDeleted: false,
      messages: [
        { id: 'msg_u', conversationId: 'conv_lease_exit', role: 'user', content: 'Can the tenant leave early?', createdAt: '2026-10-06T10:00:00.000Z', status: 'complete', intent: null, outcome: null, citations: [], suggestions: [], documentId: null },
        { id: 'msg_a', conversationId: 'conv_lease_exit', role: 'assistant', content: '', createdAt: '2026-10-06T10:00:00.000Z', status: 'streaming', intent: 'ask', outcome: null, citations: [], suggestions: [], documentId: null },
      ],
    };
    // First load: the reply is still streaming server-side. Later loads: the seeded, finished thread.
    server.use(http.get('/api/conversations/conv_lease_exit', () => HttpResponse.json(stillStreaming), { once: true }));
    renderApp('/c/conv_lease_exit');
    expect(await screen.findByText('Thinking…')).toBeInTheDocument();
    expect((await screen.findAllByText(/early termination option/i, {}, { timeout: 4000 })).length).toBeGreaterThan(0);
    expect(screen.queryByText('Thinking…')).not.toBeInTheDocument();
  });
});
