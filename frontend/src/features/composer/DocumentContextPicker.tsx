import { Check, ChevronDown, FileText, FileUp, FileX } from 'lucide-react';
import type { LegalDocument } from '@/api/types';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/components/ui/Menu';
import { Tooltip } from '@/components/ui/Tooltip';
import { truncateText } from '@/lib/format';
import { useUiStore } from '@/store/uiStore';
import styles from './Composer.module.css';

interface Props {
  documents: LegalDocument[];
  value: string | null;
  onChange: (id: string | null) => void;
}

export function DocumentContextPicker({ documents, value, onChange }: Props) {
  const requestUpload = useUiStore((s) => s.requestUpload);
  const selected = documents.find((d) => d.id === value) ?? null;
  const visible = documents.filter((d) => d.status !== 'failed');
  const blank = <span className={styles.menuCheck} />;

  return (
    <Menu>
      <Tooltip content={selected ? `Answering from ${selected.name}` : 'Choose a document to answer from'}>
        <MenuTrigger asChild>
          <button
            type="button"
            className={styles.contextChip}
            data-empty={!selected || undefined}
            aria-label={selected ? `Document: ${selected.name}. Change document` : 'No document selected. Choose document'}
          >
            {selected ? <FileText size={14} aria-hidden /> : <FileX size={14} aria-hidden />}
            <span className={styles.contextName}>
              {selected ? truncateText(selected.name, 34) : 'No document'}
            </span>
            <ChevronDown size={14} aria-hidden />
          </button>
        </MenuTrigger>
      </Tooltip>
      <MenuContent side="top" align="start">
        <MenuLabel>Answer from</MenuLabel>
        {visible.length === 0 && (
          <MenuItem disabled icon={blank} onSelect={() => undefined}>
            No documents yet
          </MenuItem>
        )}
        {visible.map((d) => (
          <MenuItem
            key={d.id}
            disabled={d.status !== 'ready'}
            icon={d.id === value ? <Check size={15} /> : blank}
            onSelect={() => onChange(d.id)}
          >
            <span className={styles.menuDocName}>{d.name}</span>
            {d.status === 'processing' && <span className={styles.menuHint}>Processing…</span>}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem icon={value === null ? <Check size={15} /> : blank} onSelect={() => onChange(null)}>
          No document <span className={styles.menuHint}>drafting only</span>
        </MenuItem>
        <MenuItem icon={<FileUp size={15} />} onSelect={requestUpload}>
          Upload a document…
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
