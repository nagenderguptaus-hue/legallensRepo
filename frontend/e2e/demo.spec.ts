import { expect, test, type Page } from '@playwright/test';

/**
 * The BRD §7 demo path, end to end in a real browser against the MSW mock backend:
 * upload → ask with citations → unanswerable question → summary → draft with placeholders
 * → stop generating → reload and reopen → delete the document.
 */

const composer = (page: Page) => page.getByLabel('Message Legal Lens');

/** Waits for any reply in progress to finish (Stop → Send), then sends. */
async function send(page: Page, text: string) {
  await expect(page.getByRole('button', { name: 'Stop generating' })).toHaveCount(0);
  await composer(page).fill(text);
  await composer(page).press('Enter');
}

async function setMock(page: Page, settings: Record<string, boolean>) {
  await page.evaluate(async (body) => {
    await fetch('/api/__mock/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }, settings);
}

test('BRD demo path', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => fetch('/api/__mock/reset', { method: 'POST' }));
  await page.reload();

  // 1. Upload a document and watch it process.
  await page.locator('input[type=file]').setInputFiles({
    name: 'Supply_Agreement.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.7 demo'.padEnd(200_000, ' ')),
  });
  await expect(page.getByRole('progressbar', { name: 'Processing Supply_Agreement.pdf' })).toBeVisible();

  // 2. Ask with citations (the lease is the default Ready document).
  await expect(page.getByRole('button', { name: /^Document: Commercial_Lease_Agreement\.pdf/ })).toBeVisible();
  await send(page, 'Can the tenant terminate the lease early?');
  await expect(page.getByText(/early termination option/i)).toBeVisible();
  const chip = page.getByRole('button', { name: /^Source 1: Commercial_Lease_Agreement\.pdf, page 18/ }).first();
  await chip.click();
  await expect(page.locator('mark', { hasText: 'Tenant may terminate this Lease' })).toBeVisible();

  // 3. Follow-up the document can't answer.
  await send(page, 'Does the lease include a non-compete clause?');
  await expect(page.getByText('Not found in the document')).toBeVisible();

  // 4. Summary.
  await send(page, 'Summarize this lease');
  await expect(page.getByRole('article', { name: 'Document summary' })).toBeVisible();

  // 5. Draft with visible placeholders.
  await send(page, 'Draft a memo on my exit options');
  await expect(page.getByRole('article', { name: 'Draft legal memo' })).toBeVisible();
  await expect(page.getByText(/need your input/)).toBeVisible();

  // 6. Stop generating mid-answer (slow model).
  await setMock(page, { slowStream: true });
  await send(page, 'What is the monthly rent?');
  await page.getByRole('button', { name: 'Stop generating' }).click();
  await expect(page.getByText('Stopped. This response may be incomplete.')).toBeVisible();
  await setMock(page, { slowStream: false });

  // 7. Reload: the conversation is still there.
  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(page.getByText(/early termination option/i).first()).toBeVisible();
  await expect(page.getByText('Stopped. This response may be incomplete.')).toBeVisible();

  // 8. Delete the document; the conversation is marked "source deleted".
  const showDocuments = page.getByRole('button', { name: 'Show documents' });
  if (await showDocuments.isVisible()) await showDocuments.click();
  await page.getByRole('tab', { name: 'Library' }).click();
  await page.getByRole('button', { name: 'Options for Commercial_Lease_Agreement.pdf' }).click();
  await page.getByRole('menuitem', { name: 'Delete document' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete document' }).click();
  await expect(page.getByText('Source document deleted')).toBeVisible();
});
