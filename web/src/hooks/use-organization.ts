"use client";

import { useQuery } from "@tanstack/react-query";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { fetchWithAuth } from "@/lib/api-client";

export interface Organization {
  id: number;
  name: string;
  is_personal: boolean;
  role: "owner" | "admin" | "member" | "viewer";
  created_at: string;
}

interface OrganizationState {
  activeOrganizationId: number | null;
  setActiveOrganizationId: (organizationId: number | null) => void;
}

export const useOrganizationStore = create<OrganizationState>()(
  persist(
    (set) => ({
      activeOrganizationId: null,
      setActiveOrganizationId: (activeOrganizationId) => set({ activeOrganizationId }),
    }),
    { name: "tenderflow-active-organization" },
  ),
);

export function useOrganizations() {
  return useQuery({
    queryKey: ["organizations"],
    queryFn: () => fetchWithAuth<Organization[]>("/api/v1/organizations"),
    select: (organizations) => (Array.isArray(organizations) ? organizations : []),
    staleTime: 5 * 60_000,
  });
}

export function useActiveOrganizationId(): number | null {
  const selected = useOrganizationStore((state) => state.activeOrganizationId);
  const organizations = useOrganizations();
  if (selected && !organizations.data) {
    return selected;
  }
  if (selected && organizations.data?.some((organization) => organization.id === selected)) {
    return selected;
  }
  return organizations.data?.[0]?.id ?? null;
}
