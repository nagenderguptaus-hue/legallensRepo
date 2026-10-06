import type { Citation } from '@/api/types';
import { Tooltip } from '@/components/ui/Tooltip';
import { truncateText } from '@/lib/format';
import { useUiStore } from '@/store/uiStore';
import styles from './CitationChip.module.css';

export function CitationChip({ index, citation }: { index: number; citation: Citation | undefined }) {
  const openSource = useUiStore((s) => s.openSource);

  if (!citation) {
    // The marker has streamed in but its citation event hasn't arrived yet.
    return (
      <span className={styles.pending} aria-label={`Citation ${index}, verifying`}>
        {index}
      </span>
    );
  }

  return (
    <Tooltip
      content={
        <span className={styles.preview}>
          <strong>{citation.documentName}</strong>
          <span className={styles.previewMeta}>
            Page {citation.page}
            {citation.section && ` · ${citation.section}`}
          </span>
          <span className={styles.previewQuote}>“{truncateText(citation.quote, 180)}”</span>
        </span>
      }
    >
      <button
        type="button"
        className={styles.chip}
        aria-label={`Source ${index}: ${citation.documentName}, page ${citation.page}`}
        onClick={(e) =>
          openSource({
            documentId: citation.documentId,
            documentName: citation.documentName,
            page: citation.page,
            quote: citation.quote,
            returnFocusTo: e.currentTarget,
          })
        }
      >
        {index}
      </button>
    </Tooltip>
  );
}
