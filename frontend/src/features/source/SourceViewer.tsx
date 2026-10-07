import { ChevronLeft, ChevronRight, CornerUpLeft, FileText, FileX2, Quote, ScanText } from 'lucide-react';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { ApiError } from '@/api/client';
import { Badge } from '@/components/ui/Badge';
import { Button, IconButton } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { Skeleton } from '@/components/ui/Skeleton';
import { useDocumentPage } from '@/hooks/queries';
import { findQuote } from '@/lib/quote';
import { useUiStore, type SourceTarget } from '@/store/uiStore';
import styles from './SourceViewer.module.css';

export function SourceViewer() {
  const source = useUiStore((s) => s.source);

  if (!source) {
    return (
      <div className={styles.empty}>
        <Quote size={22} aria-hidden />
        <p className={styles.emptyTitle}>See the evidence</p>
        <p>Select a citation in any answer to open the exact passage it came from.</p>
      </div>
    );
  }
  // Remount per citation so page state and scroll position reset.
  return <SourcePage key={`${source.documentId}:${source.page}:${source.quote}`} source={source} />;
}

function SourcePage({ source }: { source: SourceTarget }) {
  const [page, setPage] = useState(source.page);
  const { data, isPending, isError, error } = useDocumentPage(source.documentId, page);
  const markRef = useRef<HTMLElement>(null);
  const isCitedPage = page === source.page;

  useEffect(() => {
    if (data && isCitedPage) {
      markRef.current?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
    }
  }, [data, isCitedPage]);

  if (isError) {
    const gone = error instanceof ApiError && error.status === 404;
    return (
      <div className={styles.viewer}>
        <Header source={source} page={page} total={null} onPage={setPage} />
        <div className={styles.body}>
          <Notice
            tone={gone ? 'warning' : 'danger'}
            icon={<FileX2 size={18} />}
            title={gone ? 'Source document no longer available' : 'Couldn’t load this page'}
          >
            {gone
              ? `“${source.documentName}” has been deleted from your library, so this citation can’t be opened.`
              : 'Check that the Legal Lens service is running, then try again.'}
          </Notice>
          {source.quote && <QuoteCard quote={source.quote} page={source.page} />}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.viewer}>
      <Header source={source} page={page} total={data?.totalPages ?? null} onPage={setPage} />
      <div className={styles.body}>
        {data?.ocr && (
          <div className={styles.ocrRow}>
            <Badge icon={<ScanText size={12} aria-hidden />}>
              OCR{data.ocrConfidence !== null && ` · ${Math.round(data.ocrConfidence * 100)}% confidence`}
            </Badge>
          </div>
        )}
        {data?.ocr && data.ocrConfidence !== null && data.ocrConfidence < 0.8 && (
          <Notice tone="warning" title="Low OCR confidence on this page">
            The scan quality is poor here. Compare the highlighted text against the original before relying on it.
          </Notice>
        )}

        <article className={styles.paper} aria-label={`Page ${page} of ${source.documentName}`}>
          {isPending ? (
            <div className={styles.skeleton}>
              <Skeleton width="55%" height={16} />
              <Skeleton />
              <Skeleton />
              <Skeleton width="80%" />
              <Skeleton />
              <Skeleton width="65%" />
            </div>
          ) : (
            data.paragraphs.map((p, i) => (
              <p key={i} className={i === 0 ? styles.heading : undefined}>
                <Highlighted text={p} quote={isCitedPage ? source.quote : null} markRef={markRef} />
              </p>
            ))
          )}
          <span className={styles.pageNumber}>— {page} —</span>
        </article>
      </div>
    </div>
  );
}

function Highlighted({
  text,
  quote,
  markRef,
}: {
  text: string;
  quote: string | null;
  markRef: RefObject<HTMLElement | null>;
}) {
  const range = findQuote(text, quote);
  if (!range) return text;
  const [start, end] = range;
  return (
    <>
      {text.slice(0, start)}
      <mark ref={markRef} className={styles.mark}>
        {text.slice(start, end)}
      </mark>
      {text.slice(end)}
    </>
  );
}

function Header({
  source,
  page,
  total,
  onPage,
}: {
  source: SourceTarget;
  page: number;
  total: number | null;
  onPage: (p: number) => void;
}) {
  const setPanelTab = useUiStore((s) => s.setPanelTab);
  return (
    <div className={styles.header}>
      <div className={styles.titleRow}>
        <FileText size={16} aria-hidden className={styles.docIcon} />
        <p className={styles.docName} title={source.documentName}>
          {source.documentName}
        </p>
      </div>
      <div className={styles.controls}>
        <div className={styles.pager}>
          <IconButton label="Previous page" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            <ChevronLeft size={16} />
          </IconButton>
          <span className={styles.pageLabel} aria-live="polite">
            Page {page}
            {total !== null && ` of ${total}`}
          </span>
          <IconButton
            label="Next page"
            size="sm"
            disabled={total === null || page >= total}
            onClick={() => onPage(page + 1)}
          >
            <ChevronRight size={16} />
          </IconButton>
        </div>
        <div className={styles.headerActions}>
          {page !== source.page && (
            <Button size="sm" variant="ghost" onClick={() => onPage(source.page)}>
              Cited page
            </Button>
          )}
          {source.returnFocusTo?.isConnected && (
            <Button
              size="sm"
              variant="ghost"
              icon={<CornerUpLeft size={14} />}
              onClick={() => source.returnFocusTo?.focus()}
            >
              Back to answer
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setPanelTab('library')}>
            Library
          </Button>
        </div>
      </div>
    </div>
  );
}

function QuoteCard({ quote, page }: { quote: string; page: number }) {
  return (
    <figure className={styles.quoteCard}>
      <blockquote>“{quote}”</blockquote>
      <figcaption>Cited from page {page}</figcaption>
    </figure>
  );
}
