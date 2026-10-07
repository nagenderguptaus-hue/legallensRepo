import { describe, expect, it } from 'vitest';
import { dateGroup, groupByDate } from './dates';
import { formatBytes, validateFile } from './files';
import { docLabel } from './format';
import { countPlaceholders, prepareMarkdown, toPlainText } from './markdown';
import { findQuote } from './quote';

describe('prepareMarkdown', () => {
  it('turns citation markers into cite links', () => {
    expect(prepareMarkdown('Rent is $46,200 [1] and rises 3% [2].')).toBe(
      'Rent is $46,200 [1](#cite-1) and rises 3% [2](#cite-2).',
    );
  });

  it('turns placeholders into placeholder links', () => {
    expect(prepareMarkdown('By [CONFIRM: date], see [CITATION NEEDED].')).toBe(
      'By [CONFIRM: date](#placeholder), see [CITATION NEEDED](#placeholder).',
    );
  });

  it('leaves partially streamed markers and existing links alone', () => {
    expect(prepareMarkdown('Streaming [1')).toBe('Streaming [1');
    expect(prepareMarkdown('[1](https://example.com)')).toBe('[1](https://example.com)');
  });

  it('counts placeholders and produces clean clipboard text', () => {
    const md = '### Title\n**To:** [CONFIRM: name]\\\nSee [CITATION NEEDED].';
    expect(countPlaceholders(md)).toBe(2);
    expect(toPlainText(md)).toBe('Title\nTo: [CONFIRM: name]\nSee [CITATION NEEDED].');
  });
});

describe('dates', () => {
  const now = new Date('2026-10-05T15:00:00');

  it('labels relative days', () => {
    expect(dateGroup('2026-10-05T08:00:00', now)).toBe('Today');
    expect(dateGroup('2026-10-04T23:59:00', now)).toBe('Yesterday');
    expect(dateGroup('2026-09-30T10:00:00', now)).toBe('Previous 7 days');
    expect(dateGroup('2026-09-15T10:00:00', now)).toBe('Previous 30 days');
    expect(dateGroup('2026-01-01T10:00:00', now)).toBe('Older');
  });

  it('groups in display order and keeps item order', () => {
    const items = [
      { id: 'a', at: '2026-10-05T14:00:00' },
      { id: 'b', at: '2026-10-05T09:00:00' },
      { id: 'c', at: '2026-10-04T09:00:00' },
      { id: 'd', at: '2025-01-01T09:00:00' },
    ];
    const groups = groupByDate(items, (i) => i.at, now);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ['Today', ['a', 'b']],
      ['Yesterday', ['c']],
      ['Older', ['d']],
    ]);
  });
});

describe('files', () => {
  const file = (name: string, size: number) => new File([new Uint8Array(size)], name);

  it('accepts PDF and DOCX within limits', () => {
    expect(validateFile(file('lease.pdf', 10))).toBeNull();
    expect(validateFile(file('nda.DOCX', 10))).toBeNull();
  });

  it('rejects other types, empty files and files over 25 MB', () => {
    expect(validateFile(file('notes.txt', 10))).toMatch(/isn’t a PDF or Word/);
    expect(validateFile(file('empty.pdf', 0))).toMatch(/is empty/);
    expect(validateFile(file('huge.pdf', 26 * 1024 * 1024))).toMatch(/25 MB or smaller/);
  });

  it('formats sizes and labels', () => {
    expect(formatBytes(86_500)).toBe('84 KB');
    expect(formatBytes(1_284_000)).toBe('1.2 MB');
    expect(docLabel('Commercial_Lease_Agreement.pdf')).toBe('Commercial Lease Agreement');
  });
});

describe('findQuote', () => {
  const page = 'Tenant shall indemnify Landlord against all claims arising from use of the Premises.';
  const highlighted = (quote: string | null) => {
    const range = findQuote(page, quote);
    return range && page.slice(...range);
  };

  it('finds a verbatim quote', () => {
    expect(highlighted('indemnify Landlord')).toBe('indemnify Landlord');
  });

  it('finds a quote the backend shortened with an ellipsis', () => {
    expect(highlighted('Tenant shall indemnify Landlord against all…')).toBe('Tenant shall indemnify Landlord against all');
    expect(highlighted('… arising from use of the Premises.')).toBe('arising from use of the Premises.');
  });

  it('returns null when the text is not on the page', () => {
    expect(highlighted('Landlord shall indemnify Tenant')).toBeNull();
    expect(highlighted('…')).toBeNull();
    expect(highlighted(null)).toBeNull();
  });
});
