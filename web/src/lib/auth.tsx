/**
 * Auth state — centralized session context.
 *
 * Provides the current user session across the app via React Context.
 * Fetch on mount, cached in React Query, shared via context.
 */
"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";

export interface AuthUser {
  user_id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  role?: string;
}

interface SessionContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  refresh: () => Promise<void>;
}

const SessionContext = React.createContext<SessionContextValue | null>(null);

/**
 * Provider that fetches /api/v1/auth/me on mount and makes the session
 * available to all children via useSession().
 */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [manualRefetch, setManualRefetch] = React.useState(0);

  const { data, isLoading, refetch } = useQuery<AuthUser | null>({
    queryKey: ["auth", "me", manualRefetch],
    queryFn: async () => {
      try {
        const res = await fetch("/api/v1/auth/me", { credentials: "include" });
        if (!res.ok) return null;
        return res.json() as Promise<AuthUser>;
      } catch {
        return null;
      }
    },
    staleTime: 10 * 60 * 1000,
    retry: false,
  });

  const value = React.useMemo(
    () => ({
      user: data ?? null,
      isLoading,
      isAuthenticated: data !== null && data !== undefined,
      isAdmin: data?.is_admin === true || data?.role === "admin",
      refresh: async () => {
        setManualRefetch((n) => n + 1);
        await refetch();
      },
    }),
    [data, isLoading, refetch],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

/**
 * Hook to access the current session.
 * Must be used within a SessionProvider.
 */
export function useSession(): SessionContextValue {
  const ctx = React.useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return ctx;
}
