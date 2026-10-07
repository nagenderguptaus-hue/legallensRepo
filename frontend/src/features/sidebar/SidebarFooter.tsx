import clsx from 'clsx';
import { FlaskConical, Keyboard, ShieldCheck } from 'lucide-react';
import { isServiceUnreachable } from '@/api/client';
import { IconButton } from '@/components/ui/Button';
import { Tooltip } from '@/components/ui/Tooltip';
import { useHealth } from '@/hooks/queries';
import { USE_MOCKS } from '@/lib/env';
import { useUiStore } from '@/store/uiStore';
import styles from './SidebarFooter.module.css';

const STATUS_TEXT = {
  ready: 'Local model ready',
  loading: 'Local model starting…',
  unavailable: 'Local model unavailable',
  offline: 'Service not reachable',
  unknown: 'Checking local model…',
} as const;

export function SidebarFooter() {
  const { data, error, isError } = useHealth();
  const status = isError
    ? isServiceUnreachable(error)
      ? 'offline'
      : 'unavailable'
    : (data?.modelRuntime ?? 'unknown');
  const setShortcutsOpen = useUiStore((s) => s.setShortcutsOpen);
  const setDemoControlsOpen = useUiStore((s) => s.setDemoControlsOpen);

  return (
    <div className={styles.footer}>
      <Tooltip
        side="top"
        content={
          status === 'ready'
            ? `${data?.model}. Runs on this computer.`
            : status === 'offline'
              ? 'Start the Legal Lens backend on this computer. This page reconnects by itself.'
              : status === 'unavailable'
                ? 'Start the local model runtime to send messages.'
              : 'Connecting to the local model runtime.'
        }
      >
        <div className={styles.status} tabIndex={0} role="status">
          <span className={clsx(styles.dot, styles[status === 'offline' ? 'unavailable' : status])} aria-hidden />
          {STATUS_TEXT[status]}
        </div>
      </Tooltip>
      <div className={styles.row}>
        <span className={styles.privacy}>
          <ShieldCheck size={14} aria-hidden />
          Private · stays on this device
        </span>
        <div className={styles.actions}>
          {USE_MOCKS && (
            <IconButton label="Demo controls" size="sm" tooltipSide="top" onClick={() => setDemoControlsOpen(true)}>
              <FlaskConical size={15} />
            </IconButton>
          )}
          <IconButton label="Keyboard shortcuts" shortcut="?" size="sm" tooltipSide="top" onClick={() => setShortcutsOpen(true)}>
            <Keyboard size={15} />
          </IconButton>
        </div>
      </div>
    </div>
  );
}
