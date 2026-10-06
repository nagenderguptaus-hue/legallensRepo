import type { Message } from '@/api/types';
import { CopyIconButton } from '@/components/ui/CopyButton';
import { formatDateTime, formatTime } from '@/lib/dates';
import styles from './Message.module.css';

export function UserMessage({ message }: { message: Message }) {
  return (
    <article className={styles.user} aria-label="Your message">
      <div className={styles.userBubble}>{message.content}</div>
      <div className={styles.userActions}>
        <time dateTime={message.createdAt} title={formatDateTime(message.createdAt)} className={styles.time}>
          {formatTime(message.createdAt)}
        </time>
        <CopyIconButton text={message.content} label="Copy message" />
      </div>
    </article>
  );
}
