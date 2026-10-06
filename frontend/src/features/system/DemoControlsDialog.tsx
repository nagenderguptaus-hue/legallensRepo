import { useQueryClient } from '@tanstack/react-query';
import { RotateCcw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog';
import { useUiStore } from '@/store/uiStore';
import styles from './SystemDialogs.module.css';

interface MockSettings {
  slowStream: boolean;
  failNextMessage: boolean;
  modelOffline: boolean;
}

const OPTIONS: { key: keyof MockSettings; label: string; hint: string }[] = [
  {
    key: 'slowStream',
    label: 'Slow local model',
    hint: 'Stream answers about 4× slower, like a CPU-only laptop.',
  },
  {
    key: 'failNextMessage',
    label: 'Fail the next answer',
    hint: 'The next reply stops halfway with an error, to show recovery.',
  },
  {
    key: 'modelOffline',
    label: 'Model runtime offline',
    hint: 'Health check reports the model as unavailable and sending is blocked.',
  },
];

/**
 * Demo-only controls for the mock backend (rendered only when mocks are on).
 * Talks to /api/__mock/* so the UI never imports mock code directly.
 */
export function DemoControlsDialog() {
  const open = useUiStore((s) => s.demoControlsOpen);
  const setOpen = useUiStore((s) => s.setDemoControlsOpen);
  const [settings, setSettings] = useState<MockSettings | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    void fetch('/api/__mock/settings')
      .then((r) => r.json() as Promise<MockSettings>)
      .then(setSettings);
  }, [open]);

  const toggle = async (key: keyof MockSettings, value: boolean) => {
    const res = await fetch('/api/__mock/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value }),
    });
    setSettings((await res.json()) as MockSettings);
    if (key === 'modelOffline') void qc.invalidateQueries({ queryKey: ['health'] });
  };

  const reset = async () => {
    await fetch('/api/__mock/reset', { method: 'POST' });
    useUiStore.setState({ drafts: {}, newChatDocument: undefined, source: null });
    await qc.resetQueries();
    setConfirmReset(false);
    setOpen(false);
    navigate('/');
    toast.success('Demo data reset', { description: 'Sample documents and conversations restored.' });
  };

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Demo controls"
        description="Simulate real-world conditions. These settings only affect the mock backend."
        width={460}
        footer={
          <Button variant="ghost" icon={<RotateCcw size={14} />} onClick={() => setConfirmReset(true)}>
            Reset demo data
          </Button>
        }
      >
        <div className={styles.options}>
          {OPTIONS.map((o) => (
            <label key={o.key} className={styles.option}>
              <input
                type="checkbox"
                checked={settings?.[o.key] ?? false}
                disabled={!settings}
                onChange={(e) => void toggle(o.key, e.target.checked)}
              />
              <span>
                <span className={styles.optionLabel}>{o.label}</span>
                <span className={styles.optionHint}>{o.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </Dialog>
      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Reset demo data?"
        description="All conversations and uploads made during the demo are removed, and the sample data is restored."
        confirmLabel="Reset"
        destructive
        onConfirm={() => void reset()}
      />
    </>
  );
}
