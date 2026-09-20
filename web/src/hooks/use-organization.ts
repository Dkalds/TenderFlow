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

/**
 * Organización con la que una pantalla pregunta a la API. **Tres** estados, no
 * dos:
 *
 * - `undefined` — todavía no se sabe. `GET /organizations` sigue en vuelo y no
 *   hay elección guardada que adelantar.
 * - `null` — ya se sabe, y no hay ninguna que mandar. Omitir `organization_id`
 *   es entonces la respuesta correcta: el backend resuelve la personal.
 * - `number` — ya se sabe cuál.
 *
 * Los dos primeros estaban colapsados en un único `null`, y la diferencia
 * importa: con un solo valor, toda consulta con ámbito salía en el primer
 * render preguntando por la personal y se corregía al siguiente. En un listado
 * eso es un parpadeo con los datos de otra organización; en una ficha
 * —`GET /pursuits/{id}`— es un 404 «Oportunidad no encontrada» con su toast
 * rojo, porque el expediente del equipo no está en la personal.
 */
export type OrganizacionActiva = number | null | undefined;

export function useActiveOrganizationId(): OrganizacionActiva {
  const selected = useOrganizationStore((state) => state.activeOrganizationId);
  const organizations = useOrganizations();
  // Una elección guardada se adelanta al listado: quien ya eligió no espera. Si
  // resulta que ya no pertenece a esa organización, los dos casos de abajo la
  // corrigen en cuanto llega la respuesta.
  if (selected && !organizations.data) {
    return selected;
  }
  if (selected && organizations.data?.some((organization) => organization.id === selected)) {
    return selected;
  }
  // Sin nada guardado no hay qué adelantar: hasta que `/organizations` conteste,
  // no se sabe contra cuál se pregunta. Un fallo no cuenta como pendiente —la
  // query sale de `pending` al agotar reintentos— y cae en el valor por defecto,
  // que es el comportamiento de siempre.
  if (organizations.isPending) {
    return undefined;
  }
  return organizacionPorDefecto(organizations.data ?? []);
}

/**
 * ¿Ya se sabe contra qué organización preguntar?
 *
 * Es el `enabled` de toda consulta con ámbito. `null` —no hay ninguna, la
 * resuelve el backend— **sí** es una respuesta y deja pasar la consulta; sólo
 * `undefined` la retiene.
 */
export function organizacionResuelta(organizationId: OrganizacionActiva): boolean {
  return organizationId !== undefined;
}

export function useOrganizationMembers(organizationId: OrganizacionActiva) {
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

export function useAddOrganizationMember(organizationId: OrganizacionActiva) {
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

export function useUpdateOrganizationMember(organizationId: OrganizacionActiva) {
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
