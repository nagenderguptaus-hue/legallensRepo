export type DateGroupLabel = 'Today' | 'Yesterday' | 'Previous 7 days' | 'Previous 30 days' | 'Older';

const ORDER: DateGroupLabel[] = ['Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days', 'Older'];

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function dateGroup(iso: string, now = new Date()): DateGroupLabel {
  const days = Math.round((startOfDay(now) - startOfDay(new Date(iso))) / 86_400_000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days <= 7) return 'Previous 7 days';
  if (days <= 30) return 'Previous 30 days';
  return 'Older';
}

/** Groups items (already sorted newest first) into sidebar sections, preserving order. */
export function groupByDate<T>(
  items: T[],
  getDate: (item: T) => string,
  now = new Date(),
): { label: DateGroupLabel; items: T[] }[] {
  const buckets = new Map<DateGroupLabel, T[]>();
  for (const item of items) {
    const label = dateGroup(getDate(item), now);
    buckets.set(label, [...(buckets.get(label) ?? []), item]);
  }
  return ORDER.filter((l) => buckets.has(l)).map((label) => ({ label, items: buckets.get(label)! }));
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

export function formatDateTime(iso: string): string {
  return `${formatDate(iso)}, ${formatTime(iso)}`;
}

export function greeting(now = new Date()): string {
  const h = now.getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}
