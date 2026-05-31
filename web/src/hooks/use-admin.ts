"use client";

import { useEffect, useState } from "react";

/**
 * Returns whether the current user is an admin.
 * Fetches from /api/v1/auth/me on mount.
 */
export function useAdmin(): boolean {
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    let cancelled = false;

    fetch("/api/v1/auth/me", { credentials: "include" })
      .then((res) => {
        if (!res.ok) return null;
        return res.json();
      })
      .then((data) => {
        if (!cancelled && data) {
          setIsAdmin(data.is_admin === true || data.role === "admin");
        }
      })
      .catch(() => {
        // Non-admin by default on error
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return isAdmin;
}
