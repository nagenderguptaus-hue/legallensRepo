/**
 * Finds a citation quote in a page paragraph. Long quotes arrive shortened with "…" at
 * either end, so the ellipsis is ignored and the remaining text must appear verbatim.
 * Returns the [start, end) range in `text`, or null.
 */
export function findQuote(text: string, quote: string | null): [number, number] | null {
  const core = quote?.replace(/^\s*(…|\.\.\.)\s*/, '').replace(/\s*(…|\.\.\.)\s*$/, '') ?? '';
  if (!core) return null;
  const at = text.indexOf(core);
  return at === -1 ? null : [at, at + core.length];
}
