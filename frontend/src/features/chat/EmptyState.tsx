import { FileSearch, FileUp, ListChecks, PenLine, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { LogoMark } from '@/components/brand/Logo';
import { Button } from '@/components/ui/Button';
import { useDocuments } from '@/hooks/queries';
import { greeting } from '@/lib/dates';
import { docLabel } from '@/lib/format';
import { useUiStore } from '@/store/uiStore';
import { useDocumentContext } from '../composer/useDocumentContext';
import styles from './EmptyState.module.css';

export function EmptyState({ children }: { children: ReactNode }) {
  const setDraft = useUiStore((s) => s.setDraft);
  const focusComposer = useUiStore((s) => s.focusComposer);
  const requestUpload = useUiStore((s) => s.requestUpload);
  const docs = useDocuments();
  const { document } = useDocumentContext(undefined);
  const hasReady = docs.data?.some((d) => d.status === 'ready') ?? false;
  const name = document ? docLabel(document.name) : 'this document';

  const suggestions = [
    {
      icon: <FileSearch size={18} aria-hidden />,
      tone: 'ask',
      title: 'Ask a question',
      prompt: `What are the key deadlines and notice requirements in ${name}?`,
    },
    {
      icon: <ListChecks size={18} aria-hidden />,
      tone: 'summary',
      title: 'Summarize',
      prompt: `Summarize ${name}`,
    },
    {
      icon: <PenLine size={18} aria-hidden />,
      tone: 'draft',
      title: 'Draft a memo',
      prompt: `Draft a memo on the main risks in ${name} for our client`,
    },
  ];

  const pick = (prompt: string) => {
    setDraft('new', prompt);
    focusComposer();
  };

  return (
    <div className={styles.empty}>
      <div className={styles.hero}>
        <LogoMark size={40} />
        <p className={styles.greeting}>{greeting()}</p>
        <h2 className={styles.heading}>How can I help with your documents?</h2>
        <p className={styles.privacy}>
          <ShieldCheck size={15} aria-hidden />
          Answers come only from your documents, with citations. Everything stays on this computer.
        </p>
      </div>

      {children}

      {docs.isSuccess && !hasReady ? (
        <div className={styles.uploadHint}>
          <FileUp size={20} aria-hidden />
          <div>
            <p className={styles.uploadTitle}>Start by adding a document</p>
            <p className={styles.uploadText}>PDF or Word, up to 25 MB. Scanned PDFs are read with OCR.</p>
          </div>
          <Button variant="primary" onClick={requestUpload}>
            Upload document
          </Button>
        </div>
      ) : (
        <div className={styles.suggestions} role="list" aria-label="Suggestions">
          {suggestions.map((s) => (
            <button
              key={s.title}
              type="button"
              role="listitem"
              className={styles.card}
              data-tone={s.tone}
              onClick={() => pick(s.prompt)}
            >
              <span className={styles.cardIcon}>{s.icon}</span>
              <span className={styles.cardTitle}>{s.title}</span>
              <span className={styles.cardPrompt}>{s.prompt}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
