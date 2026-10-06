export const PLACEHOLDER_HREF = '#placeholder';
export const CITE_HREF_PREFIX = '#cite-';

const PLACEHOLDER = /\[(CITATION NEEDED|CONFIRM:[^\]\n]*)\]/g;

/**
 * Turns inline citation markers ([1]) and draft placeholders ([CITATION NEEDED],
 * [CONFIRM: …]) into links with special hrefs, so the markdown renderer can replace
 * them with components. Partially streamed markers ("[1") are left untouched.
 */
export function prepareMarkdown(text: string): string {
  return text
    .replace(PLACEHOLDER, (_, inner: string) => `[${inner}](${PLACEHOLDER_HREF})`)
    .replace(/\[(\d{1,2})\](?!\()/g, `[$1](${CITE_HREF_PREFIX}$1)`);
}

export function countPlaceholders(text: string): number {
  return text.match(PLACEHOLDER)?.length ?? 0;
}

/** Plain-text version for the clipboard: strips markdown emphasis and heading marks. */
export function toPlainText(markdown: string): string {
  return markdown
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(^|\W)_(.+?)_(?=\W|$)/g, '$1$2')
    .replace(/\\\n/g, '\n');
}
