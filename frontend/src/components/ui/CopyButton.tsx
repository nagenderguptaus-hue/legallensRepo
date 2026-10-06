import { Check, Copy } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button, IconButton } from './Button';

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    toast.error('Couldn’t copy to the clipboard', {
      description: 'Your browser blocked clipboard access. Select the text and copy it manually.',
    });
    return false;
  }
}

function useCopied() {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(t);
  }, [copied]);
  return [copied, setCopied] as const;
}

/** Icon-only copy button; label flips to "Copied" for 2 seconds. */
export function CopyIconButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useCopied();
  return (
    <IconButton
      label={copied ? 'Copied' : label}
      size="sm"
      onClick={async () => setCopied(await copy(text))}
    >
      {copied ? <Check size={15} /> : <Copy size={15} />}
    </IconButton>
  );
}

export function CopyTextButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useCopied();
  return (
    <Button
      size="sm"
      icon={copied ? <Check size={14} /> : <Copy size={14} />}
      onClick={async () => setCopied(await copy(text))}
    >
      <span aria-live="polite">{copied ? 'Copied' : label}</span>
    </Button>
  );
}
