export const isMac =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** Formats a shortcut for display: "Mod+K" → "⌘K" on macOS, "Ctrl+K" elsewhere. */
export function shortcut(keys: string): string {
  return isMac ? keys.replace('Mod+', '⌘').replace('Shift+', '⇧') : keys.replace('Mod+', 'Ctrl+');
}

/** True when focus is in an editable element (so single-key shortcuts must not fire). */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}
