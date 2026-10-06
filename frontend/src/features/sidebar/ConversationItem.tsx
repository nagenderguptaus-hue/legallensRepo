import clsx from 'clsx';
import { Ellipsis, Pencil, Trash2 } from 'lucide-react';
import { useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router';
import type { Conversation } from '@/api/types';
import { IconButton } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/Dialog';
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui/Menu';
import { useDeleteConversation, useUpdateConversation } from '@/hooks/queries';
import { useActiveConversationId } from '@/hooks/useActiveConversationId';
import { useIsStreaming } from '@/store/chatStore';
import styles from './ConversationItem.module.css';

export function ConversationItem({ conversation }: { conversation: Conversation }) {
  const conversationId = useActiveConversationId();
  const navigate = useNavigate();
  const isActive = conversationId === conversation.id;
  const streaming = useIsStreaming(conversation.id);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conversation.title);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const update = useUpdateConversation();
  const remove = useDeleteConversation();

  const startRename = () => {
    setTitle(conversation.title);
    setEditing(true);
  };

  const finishRename = (save: boolean) => {
    setEditing(false);
    const next = title.trim();
    if (save && next && next !== conversation.title) {
      update.mutate({ id: conversation.id, title: next });
    }
  };

  const confirmDelete = () => {
    remove.mutate(conversation.id, {
      onSuccess: () => {
        setConfirmOpen(false);
        if (isActive) navigate('/');
      },
    });
  };

  return (
    <li className={clsx(styles.item, isActive && styles.active)}>
      {editing ? (
        <input
          ref={inputRef}
          className={styles.renameInput}
          value={title}
          aria-label="Conversation title"
          maxLength={120}
          autoFocus
          onFocus={(e) => e.target.select()}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => finishRename(true)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') finishRename(true);
            if (e.key === 'Escape') finishRename(false);
          }}
        />
      ) : (
        <>
          <NavLink
            to={`/c/${conversation.id}`}
            className={styles.link}
            aria-current={isActive ? 'page' : undefined}
            title={conversation.title}
          >
            {streaming && <span className={styles.streamingDot} aria-label="Generating" />}
            <span className={styles.title}>{conversation.title}</span>
          </NavLink>
          <Menu>
            <MenuTrigger asChild>
              <IconButton label={`Options for “${conversation.title}”`} size="sm" className={styles.more}>
                <Ellipsis size={16} />
              </IconButton>
            </MenuTrigger>
            <MenuContent
              align="end"
              onCloseAutoFocus={(e) => {
                if (inputRef.current) {
                  e.preventDefault();
                  inputRef.current.focus();
                }
              }}
            >
              <MenuItem icon={<Pencil size={15} />} onSelect={startRename}>
                Rename
              </MenuItem>
              <MenuItem icon={<Trash2 size={15} />} danger onSelect={() => setConfirmOpen(true)}>
                Delete
              </MenuItem>
            </MenuContent>
          </Menu>
        </>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Delete conversation?"
        description={
          <>
            “{conversation.title}” and all of its messages will be permanently deleted from this
            device. Your documents are not affected.
          </>
        }
        confirmLabel="Delete conversation"
        destructive
        loading={remove.isPending}
        onConfirm={confirmDelete}
      />
    </li>
  );
}
