"use client";

import * as React from "react";

const KEY = "licsap_search_history";
const MAX = 10;

export function useSearchHistory() {
  const [history, setHistory] = React.useState<string[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const stored = localStorage.getItem(KEY);
      return stored ? (JSON.parse(stored) as string[]) : [];
    } catch {
      return [];
    }
  });

  const addToHistory = React.useCallback((term: string) => {
    const trimmed = term.trim();
    if (trimmed.length < 2) return;
    setHistory((prev) => {
      const next = [trimmed, ...prev.filter((h) => h !== trimmed)].slice(0, MAX);
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        // localStorage unavailable (e.g. private mode with storage blocked)
      }
      return next;
    });
  }, []);

  return { history, addToHistory };
}
