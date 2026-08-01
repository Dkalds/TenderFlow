"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";

export type OrganizationRole = "owner" | "admin" | "member" | "viewer";
export type OrganizationMembershipStatus = "active" | "invited" | "suspended" | "revoked";

export interface Organization {
  id: number;
  name: string;
  is_personal: boolean;
  role: OrganizationRole;
  created_at: string;
}

export interface OrganizationMember {
  organization_id: number;
  user_id: number;
  role: OrganizationRole;
  status: OrganizationMembershipStatus;
  created_at: string;
  updated_at: string;
  display_name: string | null;
  email: string | null;
}

export interface AddOrganizationMemberInput {
  email: string;
  role: "admin" | "member" | "viewer";
}

export interface UpdateOrganizationMemberInput {
  user_id: number;
  role: OrganizationRole;
  status: OrganizationMembershipStatus;
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

export function useOrganizationMembers(organizationId: number | null) {
  return useQuery({
    queryKey: ["organization-members", organizationId],
    queryFn: () =>
      fetchWithAuth<OrganizationMember[]>(
        `/api/v1/organizations/${organizationId}/members`,
      ),
    select: (members) => (Array.isArray(members) ? members : []),
    enabled: organizationId != null,
    staleTime: 30_000,
  });
}

export function useCreateOrganization() {
  const queryClient = useQueryClient();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  return useMutation({
    mutationFn: (name: string) =>
      apiMutate<Organization>("POST", "/api/v1/organizations", { name }),
    onSuccess: async (organization) => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      setActiveOrganizationId(organization.id);
    },
  });
}

export function useAddOrganizationMember(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AddOrganizationMemberInput) =>
      apiMutate<OrganizationMember>(
        "POST",
        `/api/v1/organizations/${organizationId}/members`,
        input,
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["organization-members", organizationId] }),
  });
}

export function useUpdateOrganizationMember(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateOrganizationMemberInput) =>
      apiMutate<OrganizationMember>(
        "PUT",
        `/api/v1/organizations/${organizationId}/members/${input.user_id}`,
        input,
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["organization-members", organizationId] }),
  });
}
