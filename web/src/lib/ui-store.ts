/**
 * Global UI store — cross-component chrome state that doesn't belong in the URL.
 *
 * Coordinates the command palette (⌘K), the saved views popover and the
 * shortcuts help so that any component can drive them without prop-drilling.
 * El asistente tiene su propio almacén (`lib/asistente-store.ts`): además de
 * abrirse lleva un contexto, y hasta 2026-10 vivía aquí solo a medias.
 */
"use client";

import { create } from "zustand";

interface UiState {
  /** Command palette (⌘K) visibility. */
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  toggleCommand: () => void;

  /** Saved views popover, drivable from outside its own trigger button. */
  savedViewsOpen: boolean;
  setSavedViewsOpen: (open: boolean) => void;
  /** Open the saved views popover (and close the command palette). */
  openSavedViews: () => void;

  /** Overlay de ayuda de atajos (`?`). Sin él los atajos son indescubribles. */
  shortcutsHelpOpen: boolean;
  setShortcutsHelpOpen: (open: boolean) => void;
  toggleShortcutsHelp: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  commandOpen: false,
  setCommandOpen: (open) => set({ commandOpen: open }),
  toggleCommand: () => set((s) => ({ commandOpen: !s.commandOpen })),

  savedViewsOpen: false,
  setSavedViewsOpen: (open) => set({ savedViewsOpen: open }),
  openSavedViews: () => set({ savedViewsOpen: true, commandOpen: false }),

  shortcutsHelpOpen: false,
  setShortcutsHelpOpen: (open) => set({ shortcutsHelpOpen: open }),
  toggleShortcutsHelp: () => set((s) => ({ shortcutsHelpOpen: !s.shortcutsHelpOpen })),
}));
