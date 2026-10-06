import { CircleHelp, FileSearch, ListChecks, PenLine } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Intent } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { Tooltip } from '@/components/ui/Tooltip';

const META: Record<Intent, { label: string; icon: ReactNode; hint: string }> = {
  ask: {
    label: 'Ask',
    icon: <FileSearch size={12} aria-hidden />,
    hint: 'Answered only from your document, with citations',
  },
  summary: {
    label: 'Summary',
    icon: <ListChecks size={12} aria-hidden />,
    hint: 'Summarized section by section from your document',
  },
  draft: {
    label: 'Draft',
    icon: <PenLine size={12} aria-hidden />,
    hint: 'First draft for attorney review. Check every placeholder.',
  },
  clarify: {
    label: 'Clarify',
    icon: <CircleHelp size={12} aria-hidden />,
    hint: 'Legal Lens needs a little more detail',
  },
};

export function IntentBadge({ intent }: { intent: Intent }) {
  const meta = META[intent];
  return (
    <Tooltip content={meta.hint}>
      <span tabIndex={0} aria-label={`Intent: ${meta.label}. ${meta.hint}`}>
        <Badge tone={intent} icon={meta.icon}>
          {meta.label}
        </Badge>
      </span>
    </Tooltip>
  );
}
