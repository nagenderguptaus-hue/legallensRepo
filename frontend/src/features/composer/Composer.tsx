import clsx from 'clsx';
import { ArrowUp, Paperclip, Square } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef } from 'react';
import type { ConversationDetail } from '@/api/types';
import { IconButton } from '@/components/ui/Button';
import { useSendMessage } from '@/features/chat/useSendMessage';
import { useHealth } from '@/hooks/queries';
import { usePendingTurn } from '@/store/chatStore';
import { useUiStore } from '@/store/uiStore';
import { DocumentContextPicker } from './DocumentContextPicker';
import { useDocumentContext } from './useDocumentContext';
import styles from './Composer.module.css';

const MAX_CHARS = 8000;
const WARN_AT = 7000;
const MAX_HEIGHT = 8 * 26 + 24; // ~8 lines

interface ComposerProps {
  conversationId: string | undefined;
  conversation: ConversationDetail | undefined;
  variant: 'docked' | 'centered';
}

export function Composer({ conversationId, conversation, variant }: ComposerProps) {
  const draftKey = conversationId ?? 'new';
  const text = useUiStore((s) => s.drafts[draftKey] ?? '');
  const setDraft = useUiStore((s) => s.setDraft);
  const focusTick = useUiStore((s) => s.composerFocusTick);
  const requestUpload = useUiStore((s) => s.requestUpload);
  const pending = usePendingTurn(conversationId);
  const send = useSendMessage();
  const health = useHealth();
  const { documentId, documents, setDocumentId } = useDocumentContext(conversation);
  const ref = useRef<HTMLTextAreaElement>(null);

  const offline = health.isError || health.data?.modelRuntime === 'unavailable';
  const streaming = Boolean(pending);
  const tooLong = text.length > MAX_CHARS;
  const canSend = text.trim().length > 0 && !streaming && !offline && !tooLong;

  // Grow with content up to ~8 lines.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  // Focus on route change and when asked (New chat, suggestion cards). Skip on touch devices
  // so the on-screen keyboard doesn't pop up unasked.
  useEffect(() => {
    if (window.matchMedia('(pointer: coarse)').matches) return;
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, [conversationId, focusTick]);

  const submit = async () => {
    const value = text.trim();
    if (!canSend) return;
    setDraft(draftKey, '');
    const result = await send({ conversationId, text: value, documentId });
    if (!result.ok) {
      const key = result.conversationId ?? draftKey;
      // Don't clobber anything the user typed in the meantime.
      if (!useUiStore.getState().drafts[key]) setDraft(key, value);
    }
  };

  const placeholder = offline
    ? 'The local model is unavailable, so messages can’t be sent right now'
    : documentId
      ? 'Ask a question, request a summary, or draft a memo…'
      : 'Draft a memo, or choose a document to ask about…';

  return (
    <div className={clsx(styles.wrap, styles[variant])}>
      <form
        className={clsx(styles.composer, offline && styles.disabled)}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="composer-input" className="visually-hidden">
          Message Legal Lens
        </label>
        <textarea
          id="composer-input"
          ref={ref}
          className={styles.input}
          rows={1}
          value={text}
          placeholder={placeholder}
          disabled={offline}
          aria-describedby="composer-disclaimer"
          onChange={(e) => setDraft(draftKey, e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <div className={styles.toolbar}>
          <IconButton label="Upload a document" tooltipSide="top" onClick={requestUpload}>
            <Paperclip size={18} />
          </IconButton>
          <DocumentContextPicker documents={documents} value={documentId} onChange={setDocumentId} />
          <span className={styles.spacer} />
          {text.length > WARN_AT && (
            <span className={clsx(styles.counter, tooLong && styles.counterOver)} aria-live="polite">
              {text.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
            </span>
          )}
          {streaming ? (
            <IconButton
              label="Stop generating"
              variant="secondary"
              tooltipSide="top"
              onClick={() => pending?.controller.abort()}
            >
              <Square size={14} fill="currentColor" />
            </IconButton>
          ) : (
            <IconButton type="submit" label="Send message" shortcut="Enter" variant="primary" tooltipSide="top" disabled={!canSend}>
              <ArrowUp size={18} />
            </IconButton>
          )}
        </div>
      </form>
      <p id="composer-disclaimer" className={styles.disclaimer}>
        AI-generated content. Not legal advice. Review before use.
      </p>
    </div>
  );
}
