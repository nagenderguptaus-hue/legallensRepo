import { expect, test, type Page } from '@playwright/test';
import { fixture } from './fixtures';

/**
 * The BRD §7 demo path against the REAL backend (stand-in adapters). Unlike demo.spec.ts it
 * asserts structure and document text, never mock wording: the answers come from the
 * synthetic lease that backend/scripts/demo_documents.py builds.
 */

const LEASE = 'Commercial_Lease_Agreement.pdf';
const LEASE_RE = LEASE.replace('.', '\\.'); // for building RegExps
const composer = (page: Page) => page.getByLabel('Message Legal Lens');
const stopButton = (page: Page) => page.getByRole('button', { name: 'Stop generating' });

/** Waits for any reply in progress to finish (Stop → Send), then sends. */
async function send(page: Page, text: string) {
  await expect(stopButton(page)).toHaveCount(0);
  await composer(page).fill(text);
  await composer(page).press('Enter');
}

async function openLibrary(page: Page) {
  const showDocuments = page.getByRole('button', { name: 'Show documents' });
  if (await showDocuments.isVisible()) await showDocuments.click();
  await page.getByRole('tab', { name: 'Library' }).click();
}

const card = (page: Page, name: string) => page.getByRole('listitem').filter({ hasText: name });

// One backend for the whole file: the tests build on each other's data, in order.
test.describe.configure({ mode: 'serial' });

test('with an empty library, a question gets a friendly "needs a document" reply', async ({ page }) => {
  await page.goto('/');
  await send(page, 'What is the monthly rent?');
  await expect(page.getByText('A document is needed')).toBeVisible();
  const reply = page.getByRole('article', { name: 'Legal Lens response' });
  await expect(reply.getByRole('button', { name: 'Upload a document' })).toBeVisible();
});

test('BRD demo path against the real backend', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Local model ready')).toBeVisible();

  // 1. Upload a real PDF; ingestion runs on the backend and the card turns Ready.
  await page.locator('input[type=file]').setInputFiles(fixture(LEASE));
  await expect(card(page, LEASE).getByText('Ready')).toBeVisible();
  await expect(page.getByRole('button', { name: new RegExp(`^Document: ${LEASE.replace('.', '\\.')}`) })).toBeVisible();

  // 2. Ask: the answer quotes §5 with a citation that opens the exact passage.
  await send(page, 'Can the tenant terminate the lease early?');
  const thread = page.getByRole('region', { name: 'Conversation' });
  await expect(thread.getByText(/Tenant may terminate this Lease early/).first()).toBeVisible();
  await expect(page.getByRole('heading', { level: 1, name: 'Can the tenant terminate the lease early' })).toBeVisible();
  await page.getByRole('button', { name: new RegExp(`^Source 1: ${LEASE.replace('.', '\\.')}, page 3`) }).first().click();
  await expect(page.locator('mark', { hasText: 'Tenant may terminate this Lease early' })).toBeVisible();

  // 3. A quote the backend shortened ("…") is still highlighted on its page.
  await send(page, 'Who must indemnify the landlord and for which claims?');
  await page.getByRole('button', { name: new RegExp(`^Source 1: ${LEASE.replace('.', '\\.')}, page 4`) }).last().click();
  await expect(page.locator('mark', { hasText: 'Tenant shall indemnify, defend and hold harmless' })).toBeVisible();

  // 4. A question the lease can't answer.
  await send(page, 'Does the lease include a non-compete clause?');
  await expect(page.getByText('Not found in the document')).toBeVisible();

  // 5. Summary and 6. draft with placeholders.
  await send(page, 'Summarize this lease');
  await expect(page.getByRole('article', { name: 'Document summary' }).last()).toBeVisible();
  await send(page, 'Draft a memo on my exit options');
  await expect(page.getByRole('article', { name: 'Draft legal memo' })).toBeVisible();
  await expect(page.getByText(/need your input/)).toBeVisible();

  // 7. Stop mid-answer, then send again straight away: no "busy" rejection.
  await send(page, 'Summarize the key terms of this lease');
  await expect(stopButton(page)).toBeVisible();
  await page.waitForTimeout(400); // let a few tokens arrive
  await stopButton(page).click();
  await expect(page.getByText('Stopped. This response may be incomplete.')).toBeVisible();
  await send(page, 'What is the monthly rent?');
  await expect(thread.getByText(/monthly Base Rent of \$4,500/).first()).toBeVisible();
  await expect(page.getByText('Message not sent')).toHaveCount(0);
  // Let it finish: reloading mid-answer would (correctly) save that reply as stopped too.
  await expect(stopButton(page)).toHaveCount(0);

  // 8. Reload: the conversation, including the stopped reply, comes back from SQLite.
  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(thread.getByText(/Tenant may terminate this Lease early/).first()).toBeVisible();
  await expect(page.getByText('Stopped. This response may be incomplete.')).toBeVisible();

  // 9. A scan has no text layer: it fails with a clear message and can be retried.
  await page.locator('input[type=file]').setInputFiles(fixture('Scanned_Exhibit_A.pdf'));
  await openLibrary(page);
  const scan = card(page, 'Scanned_Exhibit_A.pdf');
  await expect(scan.getByText('Failed')).toBeVisible();
  await expect(scan.getByText(/OCR/)).toBeVisible();
  await expect(scan.getByRole('button', { name: 'Retry' })).toBeVisible();

  // 10. Duplicate upload: the server refuses it and the toast says why.
  await page.locator('input[type=file]').setInputFiles(fixture(LEASE));
  await expect(page.getByText(/already in your library/i)).toBeVisible();

  // 11. Delete the lease: the conversation is marked "source deleted".
  await page.getByRole('button', { name: `Options for ${LEASE}` }).click();
  await page.getByRole('menuitem', { name: 'Delete document' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete document' }).click();
  await expect(page.getByText('Source document deleted')).toBeVisible();
});

test('Word documents, clarify replies and conversation management', async ({ page }) => {
  await page.goto('/');

  // A DOCX goes through the same ingestion and becomes the active document.
  await page.locator('input[type=file]').setInputFiles(fixture('Mutual_NDA.docx'));
  await expect(page.getByRole('button', { name: /^Document: Mutual_NDA\.docx/ })).toBeVisible();

  // A vague message gets quick replies; clicking one sends it.
  await send(page, 'nda');
  await page.getByRole('button', { name: 'Summarize this document' }).click();
  await expect(page.getByRole('article', { name: 'Document summary' })).toBeVisible();
  await expect(page.getByText(/three \(3\) years/).first()).toBeVisible();

  // Rename, search and delete go through the real API.
  const sidebar = page.getByRole('navigation', { name: 'Conversations' });
  await page.getByRole('button', { name: 'Options for “nda”' }).click();
  await page.getByRole('menuitem', { name: 'Rename' }).click();
  const title = page.getByRole('textbox', { name: 'Conversation title' });
  await title.fill('NDA overview');
  await title.press('Enter');
  await page.reload();
  await expect(sidebar.getByRole('link', { name: 'NDA overview' })).toBeVisible();

  await page.getByRole('searchbox', { name: 'Search conversations' }).fill('overview');
  await expect(sidebar.getByRole('link', { name: 'Can the tenant terminate the lease early' })).toHaveCount(0);
  await page.getByRole('searchbox', { name: 'Search conversations' }).fill('');

  await page.getByRole('button', { name: 'Options for “NDA overview”' }).click();
  await page.getByRole('menuitem', { name: 'Delete' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete conversation' }).click();
  await expect(sidebar.getByRole('link', { name: 'NDA overview' })).toHaveCount(0);

  // An id the backend doesn't know.
  await page.goto('/c/conv_doesnotexist');
  await expect(page.getByRole('heading', { name: 'Conversation not found' })).toBeVisible();
});
