import { describe, it, expect, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useScrolledPast } from "@/hooks/use-scrolled-past";

function setupMainContent(): HTMLElement {
  const el = document.createElement("div");
  el.id = "main-content";
  document.body.appendChild(el);
  return el;
}

function scrollTo(el: HTMLElement, scrollTop: number) {
  Object.defineProperty(el, "scrollTop", { value: scrollTop, configurable: true });
  el.dispatchEvent(new Event("scroll"));
}

afterEach(() => {
  document.getElementById("main-content")?.remove();
});

describe("useScrolledPast", () => {
  it("returns false initially when the container has not scrolled", () => {
    setupMainContent();
    const { result } = renderHook(() => useScrolledPast(8));
    expect(result.current).toBe(false);
  });

  it("returns true once scrollTop exceeds the threshold", () => {
    const el = setupMainContent();
    const { result } = renderHook(() => useScrolledPast(8));

    act(() => {
      scrollTo(el, 20);
    });

    expect(result.current).toBe(true);
  });

  it("returns false when scrollTop is back at or below the threshold", () => {
    const el = setupMainContent();
    const { result } = renderHook(() => useScrolledPast(8));

    act(() => {
      scrollTo(el, 20);
    });
    expect(result.current).toBe(true);

    act(() => {
      scrollTo(el, 0);
    });
    expect(result.current).toBe(false);
  });

  it("uses the default threshold of 8 when none is provided", () => {
    const el = setupMainContent();
    const { result } = renderHook(() => useScrolledPast());

    act(() => {
      scrollTo(el, 8);
    });
    expect(result.current).toBe(false);

    act(() => {
      scrollTo(el, 9);
    });
    expect(result.current).toBe(true);
  });

  it("does nothing and does not throw when #main-content is absent", () => {
    const { result } = renderHook(() => useScrolledPast(8));
    expect(result.current).toBe(false);
  });

  it("removes the scroll listener on unmount", () => {
    const el = setupMainContent();
    const { unmount } = renderHook(() => useScrolledPast(8));
    unmount();

    // Scrolling after unmount must not throw and must not affect anything
    // (there's no result to read anymore, but this exercises cleanup).
    expect(() => scrollTo(el, 50)).not.toThrow();
  });
});
