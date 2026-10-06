import * as Tabs from '@radix-ui/react-tabs';
import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { IconButton } from '@/components/ui/Button';
import { ACCEPT_ATTR } from '@/lib/files';
import { shortcut } from '@/lib/platform';
import { useUiStore, type PanelTab } from '@/store/uiStore';
import { SourceViewer } from '../source/SourceViewer';
import { Library } from './Library';
import { useUploadFiles } from './useUploadFiles';
import styles from './DocumentsPanel.module.css';

export function DocumentsPanel() {
  const open = useUiStore((s) => s.panelOpen);
  const tab = useUiStore((s) => s.panelTab);
  const setTab = useUiStore((s) => s.setPanelTab);
  const setPanelOpen = useUiStore((s) => s.setPanelOpen);
  const uploadTick = useUiStore((s) => s.uploadRequestTick);
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadFiles = useUploadFiles();

  // The single, global file picker: anything can request it via requestUpload().
  useEffect(() => {
    if (uploadTick > 0) inputRef.current?.click();
  }, [uploadTick]);

  return (
    <aside
      id="documents-panel"
      className={styles.panel}
      data-open={open || undefined}
      aria-label="Documents"
      inert={!open}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        multiple
        hidden
        onChange={(e) => {
          uploadFiles(Array.from(e.target.files ?? []));
          e.target.value = ''; // allow re-selecting the same file
        }}
      />
      <Tabs.Root value={tab} onValueChange={(v) => setTab(v as PanelTab)} className={styles.tabsRoot}>
        <div className={styles.header}>
          <Tabs.List className={styles.tabList} aria-label="Documents panel">
            <Tabs.Trigger value="library" className={styles.tab}>
              Library
            </Tabs.Trigger>
            <Tabs.Trigger value="source" className={styles.tab}>
              Source
            </Tabs.Trigger>
          </Tabs.List>
          <IconButton
            label="Close documents"
            shortcut={shortcut('Mod+.')}
            onClick={() => {
              const returnTo = tab === 'source' ? useUiStore.getState().source?.returnFocusTo : null;
              setPanelOpen(false);
              if (returnTo?.isConnected) returnTo.focus();
            }}
          >
            <X size={18} />
          </IconButton>
        </div>
        <Tabs.Content value="library" className={styles.content}>
          <Library onPickFiles={() => inputRef.current?.click()} />
        </Tabs.Content>
        <Tabs.Content value="source" className={styles.content}>
          <SourceViewer />
        </Tabs.Content>
      </Tabs.Root>
    </aside>
  );
}
