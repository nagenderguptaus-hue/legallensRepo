import { ChevronRight } from 'lucide-react';
import type { Citation } from '@/api/types';
import { useUiStore } from '@/store/uiStore';
import styles from './SourcesList.module.css';

export function SourcesList({ citations, defaultOpen }: { citations: Citation[]; defaultOpen: boolean }) {
  const openSource = useUiStore((s) => s.openSource);
  if (citations.length === 0) return null;

  return (
    <details className={styles.sources} open={defaultOpen}>
      <summary className={styles.summary}>
        <ChevronRight size={14} className={styles.chevron} aria-hidden />
        Sources <span className={styles.count}>{citations.length}</span>
      </summary>
      <ol className={styles.list}>
        {citations.map((c) => (
          <li key={c.index}>
            <button
              type="button"
              className={styles.source}
              onClick={(e) =>
                openSource({
                  documentId: c.documentId,
                  documentName: c.documentName,
                  page: c.page,
                  quote: c.quote,
                  returnFocusTo: e.currentTarget,
                })
              }
            >
              <span className={styles.num}>{c.index}</span>
              <span className={styles.body}>
                <span className={styles.meta}>
                  <span className={styles.doc}>{c.documentName}</span>
                  <span>
                    · p. {c.page}
                    {c.section && ` · ${c.section}`}
                  </span>
                </span>
                <span className={styles.quote}>“{c.quote}”</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </details>
  );
}
