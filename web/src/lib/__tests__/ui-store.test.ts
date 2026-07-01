import { describe, it, expect, beforeEach } from "vitest";
import { useUiStore } from "@/lib/ui-store";

/** Reset store to initial state before each test. */
const initialState = {
  commandOpen: false,
  copilotOpen: false,
  copilotSeed: { q: "", key: 0 },
};

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

describe("copilot panel", () => {
  it("starts closed with empty seed", () => {
    expect(useUiStore.getState().copilotOpen).toBe(false);
    expect(useUiStore.getState().copilotSeed).toEqual({ q: "", key: 0 });
  });

  it("setCopilotOpen(true) opens the panel", () => {
    useUiStore.getState().setCopilotOpen(true);
    expect(useUiStore.getState().copilotOpen).toBe(true);
  });

  it("setCopilotOpen(false) closes the panel", () => {
    useUiStore.setState({ copilotOpen: true });
    useUiStore.getState().setCopilotOpen(false);
    expect(useUiStore.getState().copilotOpen).toBe(false);
  });

  it("openCopilot() opens without seeding", () => {
    useUiStore.getState().openCopilot();
    const state = useUiStore.getState();
    expect(state.copilotOpen).toBe(true);
    expect(state.copilotSeed).toEqual({ q: "", key: 0 });
  });

  it("openCopilot(question) opens and seeds the question", () => {
    useUiStore.getState().openCopilot("¿Cuántas licitaciones hay?");
    const state = useUiStore.getState();
    expect(state.copilotOpen).toBe(true);
    expect(state.copilotSeed.q).toBe("¿Cuántas licitaciones hay?");
    expect(state.copilotSeed.key).toBe(1);
  });

  it("openCopilot increments key on repeated calls with the same question", () => {
    useUiStore.getState().openCopilot("same question");
    useUiStore.getState().openCopilot("same question");
    expect(useUiStore.getState().copilotSeed.key).toBe(2);
  });

  it("openCopilot closes the command palette", () => {
    useUiStore.setState({ commandOpen: true });
    useUiStore.getState().openCopilot("test");
    expect(useUiStore.getState().commandOpen).toBe(false);
  });
});
