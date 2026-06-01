"use client";

import { useQuery } from "@tanstack/react-query";

interface AuthMeResponse {
  user_id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  role?: string;
}

/**
 * Hook to determine if the current user is an admin.
 *
 * Uses React Query for caching — the `/auth/me` call is shared across
 * all components that use this hook and cached for 10 minutes.
 */
export function useAdmin(): boolean {
  const { data } = useQuery<AuthMeResponse | null>({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const res = await fetch("/api/v1/auth/me", { credentials: "include" });
      if (!res.ok) return null;
      return res.json() as Promise<AuthMeResponse>;
    },
    staleTime: 10 * 60 * 1000, // 10 minutes
    retry: false,
  });

  return data?.is_admin === true || data?.role === "admin";
}
