import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDebounce } from "@/hooks/use-debounce";

describe("useDebounce", () => {
  it("returns the initial value immediately", () => {
    const { result } = renderHook(() => useDebounce("initial", 300));
    expect(result.current).toBe("initial");
  });

  it("returns the initial value before the delay expires", () => {
    const { result } = renderHook(() => useDebounce("first", 300));
    expect(result.current).toBe("first");
  });

  it("updates to the new value after the delay using fake timers", async () => {
    let value = "first";
    const { result, rerender } = renderHook(() => useDebounce(value, 100));

    expect(result.current).toBe("first");

    value = "second";
    rerender();

    // Value should still be "first" immediately after rerender
    expect(result.current).toBe("first");

    // After the debounce delay, it should update
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 150));
    });

    expect(result.current).toBe("second");
  });

  it("debounces rapid changes and only applies the last value", async () => {
    let value = "a";
    const { result, rerender } = renderHook(() => useDebounce(value, 100));

    value = "b";
    rerender();
    value = "c";
    rerender();
    value = "d";
    rerender();

    // Still the initial value before timeout
    expect(result.current).toBe("a");

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 150));
    });

    expect(result.current).toBe("d");
  });

  it("works with number values", async () => {
    let value = 0;
    const { result, rerender } = renderHook(() => useDebounce(value, 50));
    expect(result.current).toBe(0);

    value = 42;
    rerender();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });

    expect(result.current).toBe(42);
  });

  it("works with object values", async () => {
    let value = { count: 0 };
    const { result, rerender } = renderHook(() => useDebounce(value, 50));
    expect(result.current).toEqual({ count: 0 });

    value = { count: 5 };
    rerender();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });

    expect(result.current).toEqual({ count: 5 });
  });
});
