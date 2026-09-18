"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { apiGet, apiMutate, fetchWithAuth } from "@/lib/api-client";
import type {
  OrganizationMemberInvite,
  OrganizationMembershipOut,
  OrganizationMembershipUpsert,
  OrganizationSummary,
} from "@/lib/api-types";
import { organizationKeys } from "@/lib/query-keys";

/** Nombres locales estables sobre los schemas generados (ver lib/api-types.ts). */
export type Organization = OrganizationSummary;
export type OrganizationMember = OrganizationMembershipOut;
export type AddOrganizationMemberInput = OrganizationMemberInvite;
export type UpdateOrganizationMemberInput = OrganizationMembershipUpsert;
export type OrganizationRole = OrganizationSummary["role"];
export type OrganizationMembershipStatus = OrganizationMembershipOut["status"];

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
    queryKey: organizationKeys.all,
    queryFn: () => apiGet("/api/v1/organizations"),
    select: (organizations) => (Array.isArray(organizations) ? organizations : []),
    staleTime: 5 * 60_000,
  });
}

/**
 * Organización que se usa mientras la persona no haya elegido ninguna: la
 * primera de equipo y, si no pertenece a ninguno, la personal.
 *
 * `GET /organizations` devuelve la personal primero (`ORDER BY is_personal
 * DESC`), así que quedarse con la primera dejaba a cualquier miembro de un
 * equipo mirando una organización vacía —Mi Pipeline, Dirección y el resto de
 * pantallas con ámbito— hasta que encontraba el selector del menú de cuenta.
 * El trabajo compartido vive en el equipo; la personal es el caso de quien
 * todavía no tiene uno.
 */
export function organizacionPorDefecto(organizations: readonly Organization[]): number | null {
  const equipo = organizations.find((organization) => !organization.is_personal);
  return (equipo ?? organizations[0])?.id ?? null;
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
  return organizacionPorDefecto(organizations.data ?? []);
}

export function useOrganizationMembers(organizationId: number | null) {
  return useQuery({
    queryKey: organizationKeys.members(organizationId),
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
      await queryClient.invalidateQueries({ queryKey: organizationKeys.all });
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
      queryClient.invalidateQueries({ queryKey: organizationKeys.members(organizationId) }),
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
      queryClient.invalidateQueries({ queryKey: organizationKeys.members(organizationId) }),
  });
}
