import clsx from 'clsx';
import { useMemo, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Citation } from '@/api/types';
import { Tooltip } from '@/components/ui/Tooltip';
import { CITE_HREF_PREFIX, PLACEHOLDER_HREF, prepareMarkdown } from '@/lib/markdown';
import { CitationChip } from './CitationChip';
import styles from './Markdown.module.css';

interface MarkdownProps {
  content: string;
  citations: Citation[];
  variant?: 'answer' | 'summary' | 'draft';
  streaming?: boolean;
}

export function Markdown({ content, citations, variant = 'answer', streaming = false }: MarkdownProps) {
  const prepared = useMemo(() => prepareMarkdown(content), [content]);

  const components = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        if (href === PLACEHOLDER_HREF) return <Placeholder>{children}</Placeholder>;
        if (href?.startsWith(CITE_HREF_PREFIX)) {
          const index = Number(href.slice(CITE_HREF_PREFIX.length));
          return <CitationChip index={index} citation={citations.find((c) => c.index === index)} />;
        }
        return (
          <a href={href} target="_blank" rel="noreferrer noopener">
            {children}
          </a>
        );
      },
      table: ({ children }) => (
        <div className={styles.tableWrap}>
          <table>{children}</table>
        </div>
      ),
    }),
    [citations],
  );

  return (
    <div className={clsx(styles.markdown, styles[variant], streaming && styles.streaming)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {prepared}
      </ReactMarkdown>
    </div>
  );
}

function Placeholder({ children }: { children: ReactNode }) {
  const text = String(Array.isArray(children) ? children.join('') : children);
  const missingCitation = text.startsWith('CITATION NEEDED');
  return (
    <Tooltip
      content={
        missingCitation
          ? 'No source in your documents supports this point. Add an authority before relying on it.'
          : 'Legal Lens could not confirm this from your documents. Fill it in before use.'
      }
    >
      <mark className={styles.placeholder} tabIndex={0}>
        {text}
      </mark>
    </Tooltip>
  );
}
