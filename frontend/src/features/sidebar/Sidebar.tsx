import { PanelLeftClose, PanelLeftOpen, Search, SquarePen, X } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { LogoMark, Wordmark } from '@/components/brand/Logo';
import { IconButton } from '@/components/ui/Button';
import { Kbd } from '@/components/ui/Kbd';
import { Tooltip } from '@/components/ui/Tooltip';
import { shortcut } from '@/lib/platform';
import { useUiStore } from '@/store/uiStore';
import { ConversationList } from './ConversationList';
import { SidebarFooter } from './SidebarFooter';
import styles from './Sidebar.module.css';

export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const mobileOpen = useUiStore((s) => s.mobileSidebarOpen);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const setMobileOpen = useUiStore((s) => s.setMobileSidebarOpen);
  const focusComposer = useUiStore((s) => s.focusComposer);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  const newChat = () => {
    navigate('/');
    focusComposer();
  };

  return (
    <nav
      className={styles.sidebar}
      aria-label="Conversations"
      data-collapsed={collapsed || undefined}
      data-mobile-open={mobileOpen || undefined}
    >
      {/* Collapsed rail (desktop only) */}
      <div className={styles.rail}>
        <Tooltip content="Legal Lens" side="right">
          <span className={styles.railLogo}>
            <LogoMark />
          </span>
        </Tooltip>
        <IconButton label="Expand sidebar" shortcut={shortcut('Mod+B')} tooltipSide="right" onClick={toggleSidebar}>
          <PanelLeftOpen size={18} />
        </IconButton>
        <IconButton label="New chat" shortcut={shortcut('Mod+Shift+O')} tooltipSide="right" onClick={newChat}>
          <SquarePen size={18} />
        </IconButton>
        <IconButton
          label="Search conversations"
          shortcut={shortcut('Mod+K')}
          tooltipSide="right"
          onClick={() => {
            toggleSidebar();
            requestAnimationFrame(() => document.getElementById('conversation-search')?.focus());
          }}
        >
          <Search size={18} />
        </IconButton>
      </div>

      {/* Full sidebar */}
      <div className={styles.full}>
        <div className={styles.header}>
          <Wordmark />
          <IconButton
            className={styles.collapseButton}
            label="Collapse sidebar"
            shortcut={shortcut('Mod+B')}
            onClick={toggleSidebar}
          >
            <PanelLeftClose size={18} />
          </IconButton>
          <IconButton
            className={styles.closeDrawerButton}
            label="Close menu"
            onClick={() => setMobileOpen(false)}
          >
            <X size={18} />
          </IconButton>
        </div>

        <button type="button" className={styles.newChat} onClick={newChat}>
          <SquarePen size={17} aria-hidden />
          <span>New chat</span>
          <Kbd>{shortcut('Mod+Shift+O')}</Kbd>
        </button>

        <div className={styles.search}>
          <Search size={15} className={styles.searchIcon} aria-hidden />
          <input
            id="conversation-search"
            type="search"
            placeholder="Search conversations"
            aria-label="Search conversations"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setQuery('');
                (e.target as HTMLInputElement).blur();
              }
            }}
            autoComplete="off"
          />
          {!query && <Kbd>{shortcut('Mod+K')}</Kbd>}
        </div>

        <ConversationList query={query} onClearQuery={() => setQuery('')} />
        <SidebarFooter />
      </div>
    </nav>
  );
}
