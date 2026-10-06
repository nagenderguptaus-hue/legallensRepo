import clsx from 'clsx';
import { useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { DocumentsPanel } from '@/features/documents/DocumentsPanel';
import { GlobalDropOverlay } from '@/features/documents/GlobalDropOverlay';
import { Sidebar } from '@/features/sidebar/Sidebar';
import { DemoControlsDialog } from '@/features/system/DemoControlsDialog';
import { ShortcutsDialog } from '@/features/system/ShortcutsDialog';
import { USE_MOCKS } from '@/lib/env';
import { isTyping } from '@/lib/platform';
import { useUiStore } from '@/store/uiStore';
import styles from './AppShell.module.css';

export function AppShell() {
  const sidebarCollapsed = useUiStore((s) => s.sidebarCollapsed);
  const mobileSidebarOpen = useUiStore((s) => s.mobileSidebarOpen);
  const panelOpen = useUiStore((s) => s.panelOpen);
  const announcement = useUiStore((s) => s.announcement);
  const location = useLocation();
  useGlobalShortcuts();

  // On screens where the panel would cover the chat, start with it closed.
  useEffect(() => {
    if (window.matchMedia('(max-width: 1279px)').matches) useUiStore.getState().setPanelOpen(false);
  }, []);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    useUiStore.getState().setMobileSidebarOpen(false);
  }, [location.pathname]);

  return (
    <div
      className={clsx(
        styles.shell,
        sidebarCollapsed && styles.sidebarCollapsed,
        panelOpen && styles.panelOpen,
        mobileSidebarOpen && styles.mobileSidebarOpen,
      )}
    >
      <a className="skip-link" href="#composer-input">
        Skip to message box
      </a>
      <Sidebar />
      <div
        className={styles.scrim}
        aria-hidden
        onClick={() => {
          useUiStore.getState().setMobileSidebarOpen(false);
          if (window.matchMedia('(max-width: 1279px)').matches) useUiStore.getState().setPanelOpen(false);
        }}
      />
      <main className={styles.main} id="main">
        <Outlet />
      </main>
      <DocumentsPanel />
      <GlobalDropOverlay />
      <ShortcutsDialog />
      {USE_MOCKS && <DemoControlsDialog />}
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>
    </div>
  );
}

function useGlobalShortcuts() {
  const navigate = useNavigate();

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const ui = useUiStore.getState();
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();

      if (mod && e.shiftKey && key === 'o') {
        e.preventDefault();
        navigate('/');
        ui.focusComposer();
      } else if (mod && key === 'k') {
        e.preventDefault();
        if (ui.sidebarCollapsed) ui.toggleSidebar();
        if (window.matchMedia('(max-width: 1023px)').matches) ui.setMobileSidebarOpen(true);
        // wait a frame for the sidebar to render expanded
        requestAnimationFrame(() => document.getElementById('conversation-search')?.focus());
      } else if (mod && key === 'b') {
        e.preventDefault();
        ui.toggleSidebar();
      } else if (mod && key === '.') {
        e.preventDefault();
        ui.togglePanel();
      } else if (e.key === '?' && !isTyping(e.target)) {
        e.preventDefault();
        ui.setShortcutsOpen(true);
      } else if (e.key === 'Escape' && ui.mobileSidebarOpen) {
        ui.setMobileSidebarOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [navigate]);
}
