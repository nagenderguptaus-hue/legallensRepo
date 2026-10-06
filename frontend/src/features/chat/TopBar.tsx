import { Menu, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { IconButton } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { useDocuments } from '@/hooks/queries';
import { shortcut } from '@/lib/platform';
import { useUiStore } from '@/store/uiStore';
import styles from './TopBar.module.css';

export function TopBar({ title, loading = false }: { title: string; loading?: boolean }) {
  const panelOpen = useUiStore((s) => s.panelOpen);
  const togglePanel = useUiStore((s) => s.togglePanel);
  const setMobileSidebarOpen = useUiStore((s) => s.setMobileSidebarOpen);
  const processing = useDocuments().data?.filter((d) => d.status === 'processing').length ?? 0;

  return (
    <header className={styles.topbar}>
      <IconButton className={styles.menuButton} label="Open menu" onClick={() => setMobileSidebarOpen(true)}>
        <Menu size={18} />
      </IconButton>
      <h1 className={styles.title} title={title}>
        {loading ? <Skeleton width={220} height={18} /> : title}
      </h1>
      <div className={styles.right}>
        <span className={styles.panelToggle}>
          <IconButton
            label={panelOpen ? 'Hide documents' : 'Show documents'}
            shortcut={shortcut('Mod+.')}
            aria-expanded={panelOpen}
            aria-controls="documents-panel"
            onClick={togglePanel}
          >
            {panelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          </IconButton>
          {processing > 0 && !panelOpen && (
            <span className={styles.badge} aria-label={`${processing} processing`}>
              {processing}
            </span>
          )}
        </span>
      </div>
    </header>
  );
}
