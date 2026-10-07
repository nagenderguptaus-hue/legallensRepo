import { ArrowDown, FileX2 } from 'lucide-react';
import { useRef } from 'react';
import type { ConversationDetail, Message } from '@/api/types';
import { Notice } from '@/components/ui/Notice';
import { useAutoScroll } from '@/hooks/useAutoScroll';
import type { PendingTurn } from '@/store/chatStore';
import { AssistantMessage } from './AssistantMessage';
import { UserMessage } from './UserMessage';
import styles from './ChatRoute.module.css';

interface MessageListProps {
  conversation: ConversationDetail;
  pending: PendingTurn | undefined;
  onSend: (text: string) => void;
}

export function MessageList({ conversation, pending, onSend }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingIds = pending ? [pending.user.id, pending.assistant.id] : [];
  const messages = conversation.messages.filter((m) => !pendingIds.includes(m.id));
  const all: { message: Message; live: boolean }[] = [
    // `streaming` from the server = still generating elsewhere; useConversation polls it.
    ...messages.map((message) => ({ message, live: message.status === 'streaming' })),
    ...(pending
      ? [
          { message: pending.user, live: false },
          { message: pending.assistant, live: true },
        ]
      : []),
  ];

  const signal = `${all.length}:${pending?.assistant.content.length ?? 0}:${pending?.statusLabel ?? ''}`;
  const { atBottom, onScroll, scrollToBottom } = useAutoScroll(scrollRef, signal);

  /** Retry = re-send the user message that produced this answer. */
  const retry = (index: number) => {
    const question = all
      .slice(0, index)
      .reverse()
      .find((m) => m.message.role === 'user');
    if (question) onSend(question.message.content);
  };

  const lastAssistantIndex = all.map((m) => m.message.role).lastIndexOf('assistant');

  return (
    <div className={styles.scroller} ref={scrollRef} onScroll={onScroll}>
      <section className={styles.thread} aria-label="Conversation">
        {conversation.documentDeleted && (
          <Notice tone="warning" icon={<FileX2 size={18} />} title="Source document deleted">
            The document this conversation used has been removed from your library. Earlier answers
            are kept, but their citations can no longer be opened. Choose another document below to
            continue.
          </Notice>
        )}
        {all.map(({ message, live }, i) =>
          message.role === 'user' ? (
            <UserMessage key={message.id} message={message} />
          ) : (
            <AssistantMessage
              key={message.id}
              message={message}
              streaming={live}
              statusLabel={live ? pending?.statusLabel : null}
              isLast={i === lastAssistantIndex}
              onSuggestion={onSend}
              onRetry={() => retry(i)}
            />
          ),
        )}
      </section>
      {!atBottom && (
        <button type="button" className={styles.jump} onClick={scrollToBottom}>
          <ArrowDown size={15} aria-hidden /> Jump to latest
        </button>
      )}
    </div>
  );
}
