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
  ready: 'AI model ready',
  loading: 'AI model starting…',
  unavailable: 'AI model unavailable',
  offline: 'Service not reachable',
  unknown: 'Checking AI model…',
} as const;

// Hosted models (Claude) receive messages and document passages, so the wording must not
// promise that everything stays on this computer.
const HINTS = {
  local: {
    ready: 'Runs on this computer.',
    unavailable: 'Start the local model runtime to send messages.',
    loading: 'Connecting to the local model runtime.',
    privacy: 'Private · stays on this device',
    privacyHint: 'Documents, chats and the AI model all stay on this computer.',
  },
  cloud: {
    ready: 'Runs in the cloud: your messages and passages from the selected document are sent to it.',
    unavailable: 'The AI model can’t be reached. Check the API key and the network connection.',
    loading: 'Loading the search models. Messages can already be sent.',
    privacy: 'Files stay on this device · AI in the cloud',
    privacyHint:
      'Documents, the search index and chats stay on this computer. Answers come from a hosted AI model, which receives your messages and the relevant document passages.',
  },
} as const;

export function SidebarFooter() {
  const { data, error, isError } = useHealth();
  const status = isError
    ? isServiceUnreachable(error)
      ? 'offline'
      : 'unavailable'
    : (data?.modelRuntime ?? 'unknown');
  const hints = HINTS[data?.processing ?? 'local'];
  const setShortcutsOpen = useUiStore((s) => s.setShortcutsOpen);
  const setDemoControlsOpen = useUiStore((s) => s.setDemoControlsOpen);

  return (
    <div className={styles.footer}>
      <Tooltip
        side="top"
        content={
          status === 'ready'
            ? `${data?.model}. ${hints.ready}`
            : status === 'offline'
              ? 'Start the Legal Lens backend on this computer. This page reconnects by itself.'
              : status === 'unavailable'
                ? hints.unavailable
                : hints.loading
        }
      >
        <div className={styles.status} tabIndex={0} role="status">
          <span className={clsx(styles.dot, styles[status === 'offline' ? 'unavailable' : status])} aria-hidden />
          {STATUS_TEXT[status]}
        </div>
      </Tooltip>
      <div className={styles.row}>
        <Tooltip side="top" content={hints.privacyHint}>
          <span className={styles.privacy} tabIndex={0}>
            <ShieldCheck size={14} aria-hidden />
            {hints.privacy}
          </span>
        </Tooltip>
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
