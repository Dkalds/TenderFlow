"use client";

import { useEffect, useState } from "react";

/**
 * Tracks whether the `#main-content` scroll container (owned by
 * `DashboardShell`) has been scrolled past `threshold` pixels.
 *
 * SSR-safe: returns `false` on the server and until the listener attaches on
 * mount, mirroring the `typeof window === "undefined"` guard used elsewhere
 * (see `@/lib/storage`).
 */
export function useScrolledPast(threshold = 8): boolean {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const el = document.querySelector("#main-content");
    if (!el) return;

    const handleScroll = () => {
      setScrolled(el.scrollTop > threshold);
    };

    handleScroll();
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [threshold]);

  return scrolled;
}
