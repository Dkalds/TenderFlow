"use client";

import { useSession } from "@/lib/auth";

/**
 * Hook to determine if the current user is an admin.
 *
 * Uses the centralized SessionContext instead of a separate fetch.
 */
export function useAdmin(): boolean {
  const { isAdmin } = useSession();
  return isAdmin;
}
