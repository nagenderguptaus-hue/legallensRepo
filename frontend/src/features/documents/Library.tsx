import clsx from 'clsx';
import { FileUp, Upload } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { useDocuments } from '@/hooks/queries';
import { DocumentCard } from './DocumentCard';
import styles from './Library.module.css';

/** Drops are handled app-wide by GlobalDropOverlay; the dropzone only highlights. */
export function Library({ onPickFiles }: { onPickFiles: () => void }) {
  const { data, isPending, isError, refetch } = useDocuments();
  const [dragOver, setDragOver] = useState(false);

  return (
    <div className={styles.library}>
      <button
        type="button"
        className={clsx(styles.dropzone, dragOver && styles.dragOver)}
        onClick={onPickFiles}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={() => setDragOver(false)}
      >
        <span className={styles.dropIcon}>
          <Upload size={18} aria-hidden />
        </span>
        <span className={styles.dropTitle}>
          <span className={styles.link}>Upload a document</span> or drag it here
        </span>
        <span className={styles.dropHint}>PDF or Word · up to 25 MB · scanned PDFs supported</span>
      </button>

      {isPending && (
        <div className={styles.list} aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className={styles.skeletonCard}>
              <Skeleton width={36} height={36} />
              <div className={styles.skeletonLines}>
                <Skeleton width="70%" />
                <Skeleton width="45%" height={10} />
              </div>
            </div>
          ))}
        </div>
      )}

      {isError && (
        <div className={styles.empty}>
          <p>Couldn’t load your documents.</p>
          <Button size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      )}

      {data && data.length === 0 && (
        <div className={styles.empty}>
          <FileUp size={22} aria-hidden />
          <p className={styles.emptyTitle}>No documents yet</p>
          <p>Upload a contract, opinion or agreement to ask questions about it, summarize it or draft from it.</p>
        </div>
      )}

      {data && data.length > 0 && (
        <>
          <h2 className={styles.heading}>
            Your documents <span className={styles.count}>{data.length}</span>
          </h2>
          <ul className={styles.list}>
            {data.map((doc) => (
              <DocumentCard key={doc.id} document={doc} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
