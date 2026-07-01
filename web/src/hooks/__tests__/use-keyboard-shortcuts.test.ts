import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { useUiStore } from "@/lib/ui-store";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

function dispatchKey(key: string, opts: Partial<KeyboardEventInit> = {}) {
  window.dispatchEvent(new KeyboardEvent("keydown", { key, ...opts }));
}

beforeEach(() => {
  push.mockClear();
  useUiStore.setState({ commandOpen: false });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useKeyboardShortcuts", () => {
  it("Ctrl+K toggles the command palette", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("k", { ctrlKey: true });
    expect(useUiStore.getState().commandOpen).toBe(true);
  });

  it("Cmd+K (metaKey) toggles the command palette", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("k", { metaKey: true });
    expect(useUiStore.getState().commandOpen).toBe(true);
  });

  it("pressing '1' navigates to /resumen", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("1");
    expect(push).toHaveBeenCalledWith("/resumen");
  });

  it("pressing '2' navigates to /detalle", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("2");
    expect(push).toHaveBeenCalledWith("/detalle");
  });

  it("pressing '3' navigates to /competidores", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("3");
    expect(push).toHaveBeenCalledWith("/competidores");
  });

  it("pressing '4' navigates to /investigador", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("4");
    expect(push).toHaveBeenCalledWith("/investigador");
  });

  it("pressing '5' navigates to /pipeline-alertas", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("5");
    expect(push).toHaveBeenCalledWith("/pipeline-alertas");
  });

  it("ignores number shortcuts while typing in an input", () => {
    renderHook(() => useKeyboardShortcuts());
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "1", bubbles: true }));
    expect(push).not.toHaveBeenCalled();
    document.body.removeChild(input);
  });

  it("still handles Ctrl+K even when focused on an input", () => {
    renderHook(() => useKeyboardShortcuts());
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }),
    );
    expect(useUiStore.getState().commandOpen).toBe(true);
    document.body.removeChild(input);
  });

  it("'/' focuses the search input when present", () => {
    renderHook(() => useKeyboardShortcuts());
    const wrapper = document.createElement("div");
    wrapper.setAttribute("data-search-input", "");
    const input = document.createElement("input");
    wrapper.appendChild(input);
    document.body.appendChild(wrapper);
    const focusSpy = vi.spyOn(input, "focus");

    dispatchKey("/");
    expect(focusSpy).toHaveBeenCalled();
    document.body.removeChild(wrapper);
  });

  it("Escape clicks the close-panel button when present", () => {
    renderHook(() => useKeyboardShortcuts());
    const btn = document.createElement("button");
    btn.setAttribute("data-close-panel", "");
    document.body.appendChild(btn);
    const clickSpy = vi.spyOn(btn, "click");

    dispatchKey("Escape");
    expect(clickSpy).toHaveBeenCalled();
    document.body.removeChild(btn);
  });

  it("does nothing for an unmapped key", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("z");
    expect(push).not.toHaveBeenCalled();
  });

  it("removes the listener on unmount", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderHook(() => useKeyboardShortcuts());
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
  });
});
