import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from 'react';

const THRESHOLD = 96;

/**
 * Keeps a scroll container pinned to the bottom while content grows, but stops
 * following as soon as the user scrolls up (and offers a way back down).
 * `signal` should change whenever content changes.
 */
export function useAutoScroll(ref: RefObject<HTMLElement | null>, signal: unknown) {
  const stick = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < THRESHOLD;
    stick.current = bottom;
    setAtBottom(bottom);
  }, [ref]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [ref, signal]);

  const scrollToBottom = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    stick.current = true;
    setAtBottom(true);
  }, [ref]);

  return { atBottom, onScroll, scrollToBottom };
}
