import { MessageSquareX } from 'lucide-react';
import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { Composer } from '@/features/composer/Composer';
import { useDocumentContext } from '@/features/composer/useDocumentContext';
import { ModelBanner } from '@/features/system/ModelBanner';
import { useConversation } from '@/hooks/queries';
import { truncateText } from '@/lib/format';
import { usePendingTurn } from '@/store/chatStore';
import { EmptyState } from './EmptyState';
import { MessageList } from './MessageList';
import { TopBar } from './TopBar';
import { useSendMessage } from './useSendMessage';
import styles from './ChatRoute.module.css';

export function ChatRoute() {
  const { conversationId } = useParams();
  const conversation = useConversation(conversationId);
  const pending = usePendingTurn(conversationId);
  const { documentId } = useDocumentContext(conversation.data);
  const send = useSendMessage();
  const navigate = useNavigate();

  // A brand-new chat is titled server-side when the reply finishes; until then show the question.
  const rawTitle = conversationId ? conversation.data?.title : undefined;
  const title =
    rawTitle === 'New conversation' && pending ? truncateText(pending.user.content, 60) : rawTitle;
  useEffect(() => {
    document.title = title ? `${title} · Legal Lens` : 'Legal Lens';
  }, [title]);

  const sendText = (text: string) => {
    if (pending) return;
    void send({ conversationId, text, documentId });
  };

  // ---- new chat
  if (!conversationId) {
    return (
      <div className={styles.chat}>
        <TopBar title="New chat" />
        <ModelBanner />
        <div className={styles.emptyWrap}>
          <EmptyState>
            <Composer conversationId={undefined} conversation={undefined} variant="centered" />
          </EmptyState>
        </div>
      </div>
    );
  }

  // ---- missing conversation
  if (conversation.isError) {
    const notFound = conversation.error instanceof ApiError && conversation.error.status === 404;
    return (
      <div className={styles.chat}>
        <TopBar title="Conversation" />
        <div className={styles.centerMessage} role="alert">
          <MessageSquareX size={28} aria-hidden />
          <h1>{notFound ? 'Conversation not found' : 'Couldn’t load this conversation'}</h1>
          <p>
            {notFound
              ? 'It may have been deleted. Start a new chat or pick another conversation from the sidebar.'
              : 'Check that the Legal Lens service is running, then try again.'}
          </p>
          <div className={styles.centerActions}>
            {!notFound && <Button onClick={() => void conversation.refetch()}>Try again</Button>}
            <Button variant="primary" onClick={() => navigate('/')}>
              New chat
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.chat}>
      <TopBar title={title ?? ''} loading={conversation.isPending} />
      <ModelBanner />
      {conversation.isPending ? (
        <ThreadSkeleton />
      ) : (
        <MessageList
          key={conversationId}
          conversation={conversation.data}
          pending={pending}
          onSend={sendText}
        />
      )}
      <div className={styles.dock}>
        <Composer conversationId={conversationId} conversation={conversation.data} variant="docked" />
      </div>
    </div>
  );
}

function ThreadSkeleton() {
  return (
    <div className={styles.scroller} aria-busy="true" aria-label="Loading conversation">
      <div className={styles.thread}>
        <div className={styles.skeletonUser}>
          <Skeleton width={260} height={40} />
        </div>
        <div className={styles.skeletonAssistant}>
          <Skeleton width={60} height={20} />
          <Skeleton width="92%" />
          <Skeleton width="86%" />
          <Skeleton width="60%" />
        </div>
      </div>
    </div>
  );
}
