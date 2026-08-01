import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { NUMBER_SHORTCUTS, useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
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
  useUiStore.setState({ commandOpen: false, shortcutsHelpOpen: false });
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

  it.each(NUMBER_SHORTCUTS.map((s) => [s.key, s.href] as const))(
    "pressing '%s' navigates to %s",
    (key, href) => {
      renderHook(() => useKeyboardShortcuts());
      dispatchKey(key);
      expect(push).toHaveBeenCalledWith(href);
    },
  );

  it("reaches the two primary product spaces, not only the legacy pages", () => {
    // Los atajos apuntaban a las cinco páginas analíticas legacy; Radar y
    // Oportunidades, que el producto declara primarios, no tenían ninguno.
    const destinations = NUMBER_SHORTCUTS.map((s) => s.href);
    expect(destinations).toContain("/radar");
    expect(destinations).toContain("/oportunidades");
  });

  it("ignores number shortcuts inside a contenteditable", () => {
    // El guard sólo excluía input/textarea, así que escribir en un editor rico
    // navegaba fuera de la página.
    renderHook(() => useKeyboardShortcuts());
    const editor = document.createElement("div");
    editor.contentEditable = "true";
    // jsdom no implementa `isContentEditable` a partir del atributo.
    Object.defineProperty(editor, "isContentEditable", { value: true });
    document.body.appendChild(editor);

    editor.dispatchEvent(new KeyboardEvent("keydown", { key: "1", bubbles: true }));

    expect(push).not.toHaveBeenCalled();
    document.body.removeChild(editor);
  });

  it("ignores number shortcuts inside a listbox that does its own typeahead", () => {
    renderHook(() => useKeyboardShortcuts());
    const listbox = document.createElement("div");
    listbox.setAttribute("role", "listbox");
    const option = document.createElement("div");
    listbox.appendChild(option);
    document.body.appendChild(listbox);

    option.dispatchEvent(new KeyboardEvent("keydown", { key: "2", bubbles: true }));

    expect(push).not.toHaveBeenCalled();
    document.body.removeChild(listbox);
  });

  it("leaves modified number keys to the browser", () => {
    // Alt+1 / Ctrl+1 cambian de pestaña; interceptarlos rompía el navegador.
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("1", { altKey: true });
    expect(push).not.toHaveBeenCalled();
  });

  it("'?' opens the shortcuts help overlay", () => {
    renderHook(() => useKeyboardShortcuts());
    dispatchKey("?");
    expect(useUiStore.getState().shortcutsHelpOpen).toBe(true);
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
