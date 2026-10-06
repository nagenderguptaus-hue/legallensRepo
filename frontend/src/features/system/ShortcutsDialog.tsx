import { Dialog } from '@/components/ui/Dialog';
import { Kbd } from '@/components/ui/Kbd';
import { shortcut } from '@/lib/platform';
import { useUiStore } from '@/store/uiStore';
import styles from './SystemDialogs.module.css';

const SHORTCUTS: [string, string][] = [
  ['New chat', 'Mod+Shift+O'],
  ['Search conversations', 'Mod+K'],
  ['Toggle sidebar', 'Mod+B'],
  ['Toggle documents panel', 'Mod+.'],
  ['Send message', 'Enter'],
  ['New line in message', 'Shift+Enter'],
  ['Close menus and dialogs', 'Esc'],
  ['Show this list', '?'],
];

export function ShortcutsDialog() {
  const open = useUiStore((s) => s.shortcutsOpen);
  const setOpen = useUiStore((s) => s.setShortcutsOpen);
  return (
    <Dialog open={open} onOpenChange={setOpen} title="Keyboard shortcuts" width={420}>
      <dl className={styles.shortcuts}>
        {SHORTCUTS.map(([label, keys]) => (
          <div key={label} className={styles.shortcutRow}>
            <dt>{label}</dt>
            <dd>
              <Kbd>{shortcut(keys)}</Kbd>
            </dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
