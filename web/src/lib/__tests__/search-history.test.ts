import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSearchHistory } from "@/lib/search-history";

const KEY = "licsap_search_history";

describe("useSearchHistory", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("initialises with empty history when localStorage is empty", () => {
    const { result } = renderHook(() => useSearchHistory());
    expect(result.current.history).toEqual([]);
  });

  it("addToHistory adds a term to the front of history", () => {
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory("contrato"));
    expect(result.current.history).toEqual(["contrato"]);
  });

  it("addToHistory deduplicates — repeated term moves to front", () => {
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory("contrato"));
    act(() => result.current.addToHistory("licitacion"));
    act(() => result.current.addToHistory("contrato"));
    expect(result.current.history).toEqual(["contrato", "licitacion"]);
  });

  it("ignores blank terms (empty string)", () => {
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory(""));
    expect(result.current.history).toEqual([]);
  });

  it("ignores single-character terms", () => {
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory("a"));
    expect(result.current.history).toEqual([]);
  });

  it("accepts exactly two-character terms", () => {
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory("ok"));
    expect(result.current.history).toEqual(["ok"]);
  });

  it("caps history at 10 items", () => {
    const { result } = renderHook(() => useSearchHistory());
    for (let i = 1; i <= 12; i++) {
      act(() => result.current.addToHistory(`term-${i}`));
    }
    expect(result.current.history).toHaveLength(10);
    expect(result.current.history[0]).toBe("term-12");
    expect(result.current.history).not.toContain("term-1");
    expect(result.current.history).not.toContain("term-2");
  });

  it("trims whitespace before adding", () => {
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory("  espaciado  "));
    expect(result.current.history[0]).toBe("espaciado");
  });

  it("persists history to localStorage after each add", () => {
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory("guardado"));
    const stored = JSON.parse(localStorage.getItem(KEY)!) as string[];
    expect(stored).toContain("guardado");
  });

  it("reads initial history from localStorage on mount", () => {
    localStorage.setItem(KEY, JSON.stringify(["previo"]));
    const { result } = renderHook(() => useSearchHistory());
    expect(result.current.history).toContain("previo");
  });

  it("new terms are prepended before persisted history items", () => {
    localStorage.setItem(KEY, JSON.stringify(["viejo"]));
    const { result } = renderHook(() => useSearchHistory());
    act(() => result.current.addToHistory("nuevo"));
    expect(result.current.history[0]).toBe("nuevo");
    expect(result.current.history[1]).toBe("viejo");
  });
});
