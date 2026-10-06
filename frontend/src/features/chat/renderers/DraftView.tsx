import { PenLine, TriangleAlert } from 'lucide-react';
import type { Message } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { CopyTextButton } from '@/components/ui/CopyButton';
import { Tooltip } from '@/components/ui/Tooltip';
import { pluralize } from '@/lib/format';
import { countPlaceholders, toPlainText } from '@/lib/markdown';
import { Markdown } from '../Markdown';
import styles from './Renderers.module.css';

export function DraftView({ message, streaming }: { message: Message; streaming: boolean }) {
  const kind = /CASE BRIEF/.test(message.content) ? 'Case brief' : 'Legal memo';
  const placeholders = countPlaceholders(message.content);

  return (
    <article className={styles.draftCard} aria-label={`Draft ${kind.toLowerCase()}`}>
      <header className={styles.draftToolbar}>
        <span className={styles.cardTitle}>
          <PenLine size={16} aria-hidden />
          Draft <span className={styles.cardSubtitle}>· {kind}</span>
        </span>
        <span className={styles.toolbarRight}>
          {!streaming && placeholders > 0 && (
            <Tooltip content="Highlighted items could not be confirmed from your documents. Fill them in before use.">
              <span tabIndex={0}>
                <Badge tone="warning" icon={<TriangleAlert size={12} aria-hidden />}>
                  {pluralize(placeholders, 'item')} need your input
                </Badge>
              </span>
            </Tooltip>
          )}
          {!streaming && <CopyTextButton text={toPlainText(message.content)} label="Copy draft" />}
        </span>
      </header>
      <div className={styles.paper}>
        <Markdown content={message.content} citations={message.citations} variant="draft" streaming={streaming} />
      </div>
    </article>
  );
}
