import { describe, it, expect, beforeEach } from "vitest";
import { useUiStore } from "@/lib/ui-store";

/** Reset store to initial state before each test. */
const initialState = {
  commandOpen: false,
  savedViewsOpen: false,
};

// El asistente (antes «copiloto») tiene su propio almacén y sus casos —abrir,
// sembrar una pregunta, cerrar la paleta al abrirse— están en
// `asistente-store.test.ts`.

beforeEach(() => {
  useUiStore.setState(initialState);
});

describe("command palette", () => {
  it("starts closed", () => {
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("setCommandOpen(true) opens the palette", () => {
    useUiStore.getState().setCommandOpen(true);
    expect(useUiStore.getState().commandOpen).toBe(true);
  });

  it("setCommandOpen(false) closes the palette", () => {
    useUiStore.setState({ commandOpen: true });
    useUiStore.getState().setCommandOpen(false);
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("toggleCommand flips closed → open", () => {
    useUiStore.getState().toggleCommand();
    expect(useUiStore.getState().commandOpen).toBe(true);
  });

  it("toggleCommand flips open → closed", () => {
    useUiStore.setState({ commandOpen: true });
    useUiStore.getState().toggleCommand();
    expect(useUiStore.getState().commandOpen).toBe(false);
  });
});

describe("saved views popover", () => {
  it("starts closed", () => {
    expect(useUiStore.getState().savedViewsOpen).toBe(false);
  });

  it("setSavedViewsOpen(true) opens the popover", () => {
    useUiStore.getState().setSavedViewsOpen(true);
    expect(useUiStore.getState().savedViewsOpen).toBe(true);
  });

  it("setSavedViewsOpen(false) closes the popover", () => {
    useUiStore.setState({ savedViewsOpen: true });
    useUiStore.getState().setSavedViewsOpen(false);
    expect(useUiStore.getState().savedViewsOpen).toBe(false);
  });

  it("openSavedViews() opens the popover", () => {
    useUiStore.getState().openSavedViews();
    expect(useUiStore.getState().savedViewsOpen).toBe(true);
  });

  it("openSavedViews() closes the command palette", () => {
    useUiStore.setState({ commandOpen: true });
    useUiStore.getState().openSavedViews();
    expect(useUiStore.getState().commandOpen).toBe(false);
  });
});
