/**
 * Global UI store — cross-component chrome state that doesn't belong in the URL.
 *
 * Coordinates the command palette (⌘K) and the global copilot panel so that any
 * component (hero ask-bar, command palette, keyboard shortcuts) can drive them
 * without prop-drilling or duplicate panel instances.
 */
"use client";

import { create } from "zustand";

interface UiState {
  /** Command palette (⌘K) visibility. */
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  toggleCommand: () => void;

  /** Global copilot slide-over. */
  copilotOpen: boolean;
  /** Question to seed into the copilot; `key` bumps to re-run the same text. */
  copilotSeed: { q: string; key: number };
  setCopilotOpen: (open: boolean) => void;
  /** Open the copilot, optionally seeding (and running) a question. */
  openCopilot: (question?: string) => void;

  /** Saved views popover, drivable from outside its own trigger button. */
  savedViewsOpen: boolean;
  setSavedViewsOpen: (open: boolean) => void;
  /** Open the saved views popover (and close the command palette). */
  openSavedViews: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  commandOpen: false,
  setCommandOpen: (open) => set({ commandOpen: open }),
  toggleCommand: () => set((s) => ({ commandOpen: !s.commandOpen })),

  copilotOpen: false,
  copilotSeed: { q: "", key: 0 },
  setCopilotOpen: (open) => set({ copilotOpen: open }),
  openCopilot: (question) =>
    set((s) => ({
      copilotOpen: true,
      commandOpen: false,
      copilotSeed: question
        ? { q: question, key: s.copilotSeed.key + 1 }
        : s.copilotSeed,
    })),

  savedViewsOpen: false,
  setSavedViewsOpen: (open) => set({ savedViewsOpen: open }),
  openSavedViews: () => set({ savedViewsOpen: true, commandOpen: false }),
}));
