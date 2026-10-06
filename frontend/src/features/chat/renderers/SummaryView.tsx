import { ListChecks } from 'lucide-react';
import type { Message } from '@/api/types';
import { CopyTextButton } from '@/components/ui/CopyButton';
import { toPlainText } from '@/lib/markdown';
import { Markdown } from '../Markdown';
import styles from './Renderers.module.css';

export function SummaryView({ message, streaming }: { message: Message; streaming: boolean }) {
  const documentName = message.citations[0]?.documentName;
  return (
    <article className={styles.summaryCard} aria-label="Document summary">
      <header className={styles.cardHeader}>
        <span className={styles.cardTitle}>
          <ListChecks size={16} aria-hidden />
          Summary{documentName && <span className={styles.cardSubtitle}>· {documentName}</span>}
        </span>
        {!streaming && <CopyTextButton text={toPlainText(message.content)} label="Copy summary" />}
      </header>
      <div className={styles.cardBody}>
        <Markdown content={message.content} citations={message.citations} variant="summary" streaming={streaming} />
      </div>
    </article>
  );
}
