export function truncateText(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/** "Commercial_Lease_Agreement.pdf" → "Commercial Lease Agreement" */
export function docLabel(fileName: string): string {
  return fileName.replace(/\.(pdf|docx)$/i, '').replace(/[_-]+/g, ' ').trim();
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
