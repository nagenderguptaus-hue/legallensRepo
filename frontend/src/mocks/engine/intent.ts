import type { Intent } from '@/api/types';

/**
 * Keyword stand-in for the LLM intent router. The real router uses structured LLM output;
 * this mirrors its four labels so every UI branch can be exercised.
 */
export function detectIntent(message: string): Intent {
  const m = message.toLowerCase().trim();
  if (/\b(summar|overview|tl;?dr|gist|key points|key terms|outline of)/.test(m)) return 'summary';
  if (
    /\b(draft|write|prepare|compose)\b/.test(m) ||
    /\b(memo|memorandum|case brief|brief me a)\b/.test(m)
  ) {
    return 'draft';
  }
  const words = m.split(/\s+/).filter(Boolean);
  if (words.length <= 2 && !m.endsWith('?')) return 'clarify';
  return 'ask';
}

const FOLLOW_UP = /\b(that|this|it|its|those|they|them|these|there|the same|he|she)\b/;

/** True when a message only makes sense with earlier context (drives the query editor). */
export function isFollowUp(message: string): boolean {
  const words = message.trim().split(/\s+/).length;
  return words <= 12 && FOLLOW_UP.test(message.toLowerCase());
}
