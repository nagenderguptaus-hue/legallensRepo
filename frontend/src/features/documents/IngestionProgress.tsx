import type { IngestionStage, LegalDocument } from '@/api/types';
import styles from './DocumentCard.module.css';

const LABELS: Record<IngestionStage, string> = {
  validating: 'Checking file',
  extracting: 'Reading text',
  ocr: 'Running OCR',
  quality_check: 'Checking layout quality',
  chunking: 'Splitting into sections',
  indexing: 'Building search index',
};

const ORDER: IngestionStage[] = ['validating', 'extracting', 'quality_check', 'chunking', 'indexing'];

export function IngestionProgress({ document: doc }: { document: LegalDocument }) {
  const stage = doc.stage ?? 'validating';
  const step = ORDER.indexOf(stage === 'ocr' ? 'extracting' : stage);
  const fraction = doc.progress ? doc.progress.current / doc.progress.total : 0;
  const percent = Math.round(((step + fraction) / ORDER.length) * 100);
  const detail = doc.progress ? ` · page ${doc.progress.current} of ${doc.progress.total}` : '';
  const label = `${LABELS[stage]}${detail}`;

  return (
    <div className={styles.progress}>
      <div className={styles.progressText}>
        <span>{label}</span>
        <span className={styles.progressStep}>
          Step {step + 1} of {ORDER.length}
        </span>
      </div>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-label={`Processing ${doc.name}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={label}
      >
        <div className={styles.progressBar} style={{ width: `${Math.max(4, percent)}%` }} />
      </div>
    </div>
  );
}
