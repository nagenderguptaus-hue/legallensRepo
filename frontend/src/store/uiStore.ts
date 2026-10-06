import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export interface SourceTarget {
  documentId: string;
  documentName: string;
  page: number;
  quote: string | null;
  /** Element to return focus to when the viewer closes. */
  returnFocusTo?: HTMLElement | null;
}

export type PanelTab = 'library' | 'source';

/** `undefined` = automatic (latest Ready document), `null` = user chose "no document". */
export type DocumentChoice = string | null | undefined;

interface UiState {
  sidebarCollapsed: boolean;
  mobileSidebarOpen: boolean;
  panelOpen: boolean;
  panelTab: PanelTab;
  source: SourceTarget | null;
  newChatDocument: DocumentChoice;
  /** Unsent composer text per conversation ("new" for the empty state). */
  drafts: Record<string, string>;
  shortcutsOpen: boolean;
  demoControlsOpen: boolean;
  announcement: string;
  /** Bumped to ask the composer to focus itself. */
  composerFocusTick: number;
  /** Bumped to open the (single, global) file picker. */
  uploadRequestTick: number;

  toggleSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;
  setPanelOpen: (open: boolean) => void;
  togglePanel: () => void;
  setPanelTab: (tab: PanelTab) => void;
  openSource: (target: SourceTarget) => void;
  setNewChatDocument: (choice: DocumentChoice) => void;
  setDraft: (key: string, text: string) => void;
  setShortcutsOpen: (open: boolean) => void;
  setDemoControlsOpen: (open: boolean) => void;
  announce: (message: string) => void;
  focusComposer: () => void;
  requestUpload: () => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mobileSidebarOpen: false,
      panelOpen: true,
      panelTab: 'library',
      source: null,
      newChatDocument: undefined,
      drafts: {},
      shortcutsOpen: false,
      demoControlsOpen: false,
      announcement: '',
      composerFocusTick: 0,
      uploadRequestTick: 0,

      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
      setPanelOpen: (open) => set({ panelOpen: open }),
      togglePanel: () => set((s) => ({ panelOpen: !s.panelOpen })),
      setPanelTab: (tab) => set({ panelTab: tab, panelOpen: true }),
      openSource: (target) => set({ source: target, panelOpen: true, panelTab: 'source' }),
      setNewChatDocument: (choice) => set({ newChatDocument: choice }),
      setDraft: (key, text) =>
        set((s) => {
          const drafts = { ...s.drafts };
          if (text) drafts[key] = text;
          else delete drafts[key];
          return { drafts };
        }),
      setShortcutsOpen: (open) => set({ shortcutsOpen: open }),
      setDemoControlsOpen: (open) => set({ demoControlsOpen: open }),
      // Toggle a zero-width char so repeating the same message is announced again.
      announce: (message) =>
        set((s) => ({
          announcement: s.announcement === message ? message + String.fromCharCode(0x200b) : message,
        })),
      focusComposer: () => set((s) => ({ composerFocusTick: s.composerFocusTick + 1 })),
      requestUpload: () => set((s) => ({ uploadRequestTick: s.uploadRequestTick + 1 })),
    }),
    {
      name: 'legallens.ui.v1',
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        sidebarCollapsed: s.sidebarCollapsed,
        panelOpen: s.panelOpen,
        newChatDocument: s.newChatDocument,
        drafts: s.drafts,
      }),
    },
  ),
);
