import { Compass } from 'lucide-react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/Button';
import { TopBar } from '../chat/TopBar';
import styles from '../chat/ChatRoute.module.css';

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className={styles.chat}>
      <TopBar title="Page not found" />
      <div className={styles.centerMessage}>
        <Compass size={28} aria-hidden />
        <h1>This page doesn’t exist</h1>
        <p>The link may be out of date. Start a new chat or pick a conversation from the sidebar.</p>
        <div className={styles.centerActions}>
          <Button variant="primary" onClick={() => navigate('/')}>
            New chat
          </Button>
        </div>
      </div>
    </div>
  );
}
