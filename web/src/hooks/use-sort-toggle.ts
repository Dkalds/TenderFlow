"use client";

import { useState, useCallback } from "react";

export function useSortToggle<K extends string>(
  defaultKey: K,
  defaultDir: "asc" | "desc" = "desc",
) {
  const [sortKey, setSortKey] = useState<K>(defaultKey);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultDir);

  const toggleSort = useCallback(
    (key: K) => {
      if (key === sortKey) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("desc");
      }
    },
    [sortKey],
  );

  return { sortKey, sortDir, toggleSort } as const;
}
