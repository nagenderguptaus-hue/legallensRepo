import { CircleStop, FileUp, FolderOpen, RotateCcw, SearchX, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Message } from '@/api/types';
import { LogoMark } from '@/components/brand/Logo';
import { Button } from '@/components/ui/Button';
import { CopyIconButton } from '@/components/ui/CopyButton';
import { Notice } from '@/components/ui/Notice';
import { Spinner } from '@/components/ui/Spinner';
import { formatDateTime, formatTime } from '@/lib/dates';
import { toPlainText } from '@/lib/markdown';
import { useUiStore } from '@/store/uiStore';
import { IntentBadge } from './IntentBadge';
import { Markdown } from './Markdown';
import { DraftView } from './renderers/DraftView';
import { SummaryView } from './renderers/SummaryView';
import { SourcesList } from './SourcesList';
import styles from './Message.module.css';

interface AssistantMessageProps {
  message: Message;
  /** Live progress label while waiting for the first token. */
  statusLabel?: string | null;
  streaming?: boolean;
  isLast: boolean;
  onSuggestion: (text: string) => void;
  onRetry: () => void;
}

export function AssistantMessage({
  message,
  statusLabel,
  streaming = false,
  isLast,
  onSuggestion,
  onRetry,
}: AssistantMessageProps) {
  const requestUpload = useUiStore((s) => s.requestUpload);
  const setPanelTab = useUiStore((s) => s.setPanelTab);
  const waiting = streaming && !message.content;

  let body: ReactNode;
  if (waiting) {
    body = (
      <p className={styles.statusLine}>
        <Spinner size={15} />
        <span className={styles.statusText}>{statusLabel ?? 'Thinking…'}</span>
      </p>
    );
  } else if (message.outcome === 'not_found') {
    body = (
      <Notice tone="neutral" icon={<SearchX size={18} />} title="Not found in the document">
        <Markdown content={message.content} citations={[]} />
        <p className={styles.tip}>
          Try rephrasing with terms the document is likely to use, or check that the right
          document is selected.
        </p>
      </Notice>
    );
  } else if (message.outcome === 'needs_document') {
    body = (
      <Notice
        tone="info"
        icon={<FileUp size={18} />}
        title="A document is needed"
        actions={
          <>
            <Button size="sm" variant="primary" icon={<FileUp size={14} />} onClick={requestUpload}>
              Upload a document
            </Button>
            <Button size="sm" icon={<FolderOpen size={14} />} onClick={() => setPanelTab('library')}>
              Choose from library
            </Button>
          </>
        }
      >
        <Markdown content={message.content} citations={[]} />
      </Notice>
    );
  } else if (message.intent === 'summary') {
    body = <SummaryView message={message} streaming={streaming} />;
  } else if (message.intent === 'draft') {
    body = <DraftView message={message} streaming={streaming} />;
  } else {
    body = <Markdown content={message.content} citations={message.citations} streaming={streaming} />;
  }

  const longform = message.intent === 'summary' || message.intent === 'draft';
  const showActions = !streaming && message.content && message.outcome !== 'needs_document';

  return (
    <article className={styles.assistant} aria-label="Legal Lens response" aria-busy={streaming || undefined}>
      <div className={styles.avatar} aria-hidden>
        <LogoMark size={26} />
      </div>
      <div className={styles.assistantBody}>
        {message.intent && (
          <div className={styles.meta}>
            <IntentBadge intent={message.intent} />
          </div>
        )}

        {body}

        {message.intent === 'clarify' && isLast && !streaming && message.suggestions.length > 0 && (
          <div className={styles.suggestions} role="group" aria-label="Suggested replies">
            {message.suggestions.map((s) => (
              <button key={s} type="button" className={styles.suggestion} onClick={() => onSuggestion(s)}>
                {s}
              </button>
            ))}
          </div>
        )}

        {!streaming && (
          <SourcesList citations={message.citations} defaultOpen={!longform} />
        )}

        {message.status === 'stopped' && (
          <p className={styles.stopped}>
            <CircleStop size={14} aria-hidden /> Stopped. This response may be incomplete.
          </p>
        )}

        {message.status === 'error' && (
          <Notice
            tone="danger"
            role="alert"
            icon={<TriangleAlert size={18} />}
            title="This answer was interrupted"
            className={styles.errorNotice}
            actions={
              <Button size="sm" icon={<RotateCcw size={14} />} onClick={onRetry}>
                Retry
              </Button>
            }
          >
            {message.error?.message ?? 'Something went wrong while generating the answer.'}
            {message.error && message.error.request_id !== 'none' && (
              <span className={styles.ref}> Reference: {message.error.request_id}</span>
            )}
          </Notice>
        )}

        {showActions && (
          <div className={styles.actions}>
            <CopyIconButton text={toPlainText(message.content)} label="Copy response" />
            {message.status === 'stopped' && (
              <Button size="sm" variant="ghost" icon={<RotateCcw size={14} />} onClick={onRetry}>
                Regenerate
              </Button>
            )}
            <time className={styles.time} dateTime={message.createdAt} title={formatDateTime(message.createdAt)}>
              {formatTime(message.createdAt)}
            </time>
          </div>
        )}
      </div>
    </article>
  );
}
