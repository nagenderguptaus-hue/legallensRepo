import clsx from 'clsx';
import {
  CircleCheck,
  CircleX,
  Ellipsis,
  FileText,
  MessageSquarePlus,
  RotateCcw,
  ScanText,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import { useState } from 'react';
import type { LegalDocument } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { Button, IconButton } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/Dialog';
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui/Menu';
import { Spinner } from '@/components/ui/Spinner';
import { Tooltip } from '@/components/ui/Tooltip';
import { useConversation, useDeleteDocument, useRetryDocument } from '@/hooks/queries';
import { useActiveConversationId } from '@/hooks/useActiveConversationId';
import { formatDate } from '@/lib/dates';
import { formatBytes } from '@/lib/files';
import { pluralize } from '@/lib/format';
import { useUiStore } from '@/store/uiStore';
import { useDocumentContext } from '../composer/useDocumentContext';
import { IngestionProgress } from './IngestionProgress';
import styles from './DocumentCard.module.css';

export function DocumentCard({ document: doc }: { document: LegalDocument }) {
  const conversationId = useActiveConversationId();
  const conversation = useConversation(conversationId).data;
  const { documentId, setDocumentId } = useDocumentContext(conversationId ? conversation : undefined);
  const retry = useRetryDocument();
  const remove = useDeleteDocument();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const inUse = documentId === doc.id;

  const meta = [
    doc.pages ? pluralize(doc.pages, 'page') : null,
    formatBytes(doc.sizeBytes),
    formatDate(doc.uploadedAt),
  ]
    .filter(Boolean)
    .join(' · ');

  const useInChat = () => {
    setDocumentId(doc.id);
    useUiStore.getState().focusComposer();
    useUiStore.getState().announce(`Now answering from ${doc.name}.`);
  };

  return (
    <li className={clsx(styles.card, inUse && styles.inUse, doc.status === 'failed' && styles.failed)}>
      <div className={styles.top}>
        <span className={clsx(styles.fileIcon, styles[doc.type])} aria-hidden>
          <FileText size={18} />
          <span className={styles.ext}>{doc.type.toUpperCase()}</span>
        </span>
        <div className={styles.info}>
          <p className={styles.name} title={doc.name}>
            {doc.name}
          </p>
          <p className={styles.meta}>{meta}</p>
          <div className={styles.badges}>
            {doc.status === 'ready' && (
              <Badge tone="success" icon={<CircleCheck size={12} aria-hidden />}>
                Ready
              </Badge>
            )}
            {doc.status === 'processing' && (
              <Badge tone="info" icon={<Spinner size={11} />}>
                Processing
              </Badge>
            )}
            {doc.status === 'failed' && (
              <Badge tone="danger" icon={<CircleX size={12} aria-hidden />}>
                Failed
              </Badge>
            )}
            {doc.isScanned && (
              <Tooltip content="Scanned document: text was recognised with OCR">
                <span tabIndex={0}>
                  <Badge icon={<ScanText size={12} aria-hidden />}>OCR</Badge>
                </span>
              </Tooltip>
            )}
            {inUse && <Badge tone="info">In use</Badge>}
          </div>
        </div>
        {doc.status !== 'processing' && (
          <Menu>
            <MenuTrigger asChild>
              <IconButton label={`Options for ${doc.name}`} size="sm">
                <Ellipsis size={16} />
              </IconButton>
            </MenuTrigger>
            <MenuContent align="end">
              {doc.status === 'ready' && !inUse && (
                <MenuItem icon={<MessageSquarePlus size={15} />} onSelect={useInChat}>
                  Use in this chat
                </MenuItem>
              )}
              <MenuItem icon={<Trash2 size={15} />} danger onSelect={() => setConfirmOpen(true)}>
                Delete document
              </MenuItem>
            </MenuContent>
          </Menu>
        )}
      </div>

      {doc.status === 'processing' && <IngestionProgress document={doc} />}

      {doc.status === 'failed' && (
        <div className={styles.failure}>
          <p>{doc.error ?? 'Processing failed.'}</p>
          <div className={styles.actions}>
            <Button size="sm" icon={<RotateCcw size={14} />} loading={retry.isPending} onClick={() => retry.mutate(doc.id)}>
              Retry
            </Button>
            <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} onClick={() => setConfirmOpen(true)}>
              Delete
            </Button>
          </div>
        </div>
      )}

      {doc.status === 'ready' && doc.warnings.length > 0 && (
        <details className={styles.warnings}>
          <summary>
            <TriangleAlert size={14} aria-hidden />
            {pluralize(doc.warnings.length, 'warning')}
          </summary>
          <ul>
            {doc.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}

      {doc.status === 'ready' && !inUse && (
        <Button size="sm" className={styles.useButton} icon={<MessageSquarePlus size={14} />} onClick={useInChat}>
          Use in chat
        </Button>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Delete this document?"
        description={
          <>
            “{doc.name}”, its extracted text and its search index will be permanently removed from
            this device. Conversations that used it are kept, but their citations will no longer open.
          </>
        }
        confirmLabel="Delete document"
        destructive
        loading={remove.isPending}
        onConfirm={() => remove.mutate(doc, { onSuccess: () => setConfirmOpen(false) })}
      />
    </li>
  );
}
