import { MessageSquareText, SearchX } from 'lucide-react';
import { useMemo } from 'react';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { useConversations } from '@/hooks/queries';
import { groupByDate } from '@/lib/dates';
import { ConversationItem } from './ConversationItem';
import styles from './ConversationList.module.css';

export function ConversationList({ query, onClearQuery }: { query: string; onClearQuery: () => void }) {
  const { data, isPending, isError, refetch } = useConversations();
  const q = query.trim().toLowerCase();

  const groups = useMemo(() => {
    const filtered = (data ?? []).filter((c) => !q || c.title.toLowerCase().includes(q));
    return groupByDate(filtered, (c) => c.updatedAt);
  }, [data, q]);

  if (isPending) {
    return (
      <div className={styles.list} aria-busy="true" aria-label="Loading conversations">
        <div className={styles.skeletons}>
          <Skeleton width={70} height={10} />
          {[82, 64, 90, 58, 76, 68].map((w, i) => (
            <Skeleton key={i} width={`${w}%`} height={14} />
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className={styles.list}>
        <div className={styles.empty}>
          <p>Couldn’t load conversations.</p>
          <Button size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className={styles.list}>
        <div className={styles.empty}>
          <MessageSquareText size={20} aria-hidden />
          <p>No conversations yet.</p>
          <p className={styles.hint}>Your chats are saved on this device.</p>
        </div>
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className={styles.list}>
        <div className={styles.empty} role="status">
          <SearchX size={20} aria-hidden />
          <p>No conversations match “{query.trim()}”.</p>
          <Button size="sm" variant="ghost" onClick={onClearQuery}>
            Clear search
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.list}>
      {groups.map((group) => (
        <section key={group.label} aria-labelledby={`group-${group.label}`} className={styles.group}>
          <h2 id={`group-${group.label}`} className={styles.groupLabel}>
            {group.label}
          </h2>
          <ul className={styles.items}>
            {group.items.map((c) => (
              <ConversationItem key={c.id} conversation={c} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
