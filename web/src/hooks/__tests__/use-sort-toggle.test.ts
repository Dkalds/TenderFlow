import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSortToggle } from "@/hooks/use-sort-toggle";

describe("useSortToggle", () => {
  it("initialises with the given defaultKey and defaultDir", () => {
    const { result } = renderHook(() => useSortToggle("name", "asc"));
    expect(result.current.sortKey).toBe("name");
    expect(result.current.sortDir).toBe("asc");
  });

  it("defaults direction to 'desc' when not specified", () => {
    const { result } = renderHook(() => useSortToggle("name"));
    expect(result.current.sortDir).toBe("desc");
  });

  it("toggling the same key flips desc -> asc", () => {
    const { result } = renderHook(() => useSortToggle("name", "desc"));
    act(() => result.current.toggleSort("name"));
    expect(result.current.sortKey).toBe("name");
    expect(result.current.sortDir).toBe("asc");
  });

  it("toggling the same key flips asc -> desc", () => {
    const { result } = renderHook(() => useSortToggle("name", "asc"));
    act(() => result.current.toggleSort("name"));
    expect(result.current.sortKey).toBe("name");
    expect(result.current.sortDir).toBe("desc");
  });

  it("toggling a different key sets new key with 'desc' direction", () => {
    const { result } = renderHook(() => useSortToggle<"name" | "value">("name", "asc"));
    act(() => result.current.toggleSort("value"));
    expect(result.current.sortKey).toBe("value");
    expect(result.current.sortDir).toBe("desc");
  });

  it("multiple toggles on same key cycle correctly", () => {
    const { result } = renderHook(() => useSortToggle("name", "desc"));
    act(() => result.current.toggleSort("name")); // asc
    expect(result.current.sortDir).toBe("asc");
    act(() => result.current.toggleSort("name")); // desc
    expect(result.current.sortDir).toBe("desc");
  });

  it("return value has the correct shape { sortKey, sortDir, toggleSort }", () => {
    const { result } = renderHook(() => useSortToggle("name"));
    expect(result.current).toHaveProperty("sortKey");
    expect(result.current).toHaveProperty("sortDir");
    expect(result.current).toHaveProperty("toggleSort");
    expect(typeof result.current.toggleSort).toBe("function");
  });
});
