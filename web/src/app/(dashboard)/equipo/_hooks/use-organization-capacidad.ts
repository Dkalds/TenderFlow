"use client";

/**
 * Identidad fiscal y perfil de capacidad de la organización (S2.1 y S2.2).
 *
 * Vive aquí y no en `hooks/use-organization.ts` porque solo lo consume la
 * pestaña «Organización» de `/equipo`, igual que `use-invitations.ts`. Los
 * tipos salen del cliente generado (`Schemas[...]`): la forma la define el
 * backend, no este fichero.
 *
 * Los NIFs solo los sirve la API a owner/admin, así que su query se pide
 * `enabled` solo cuando quien mira puede gestionarlos: pedirla como `member`
 * daría un 403 en cada carga, ruido sin ninguna información nueva. El perfil
 * de capacidad sí lo lee cualquier miembro, `viewer` incluido — es lo que
 * explica por qué el checklist de una oportunidad dice «desconocido».
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { organizationKeys } from "@/lib/query-keys";

export type OrganizationNifs = Schemas["OrganizationNifsOut"];
export type OrganizationNifIn = Schemas["OrganizationNif"];
export type OrganizationCapabilities = Schemas["OrganizationCapabilitiesOut"];
export type OrganizationCapabilitiesIn = Schemas["OrganizationCapabilities"];
export type OrganizationCapabilityField = NonNullable<
  OrganizationCapabilities["campos_incompletos"]
>[number];

/** Claves de caché propias: `organizationKeys` no las declara y no es su fichero. */
export const capacidadKeys = {
  nifs: (organizationId: number | null) =>
    [...organizationKeys.members(organizationId), "nifs"] as const,
  capabilities: (organizationId: number | null) =>
    [...organizationKeys.members(organizationId), "capabilities"] as const,
};

export function useOrganizationNifs(organizationId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: capacidadKeys.nifs(organizationId),
    queryFn: () =>
      fetchWithAuth<OrganizationNifs>(`/api/v1/organizations/${organizationId}/nifs`),
    enabled: organizationId != null && enabled,
    staleTime: 30_000,
  });
}

export function useSaveOrganizationNifs(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (nifs: OrganizationNifIn[]) =>
      apiMutate<OrganizationNifs>("PUT", `/api/v1/organizations/${organizationId}/nifs`, {
        nifs,
      }),
    onSuccess: (data) => {
      // Se siembra la caché con la respuesta en vez de invalidar: el PUT
      // devuelve exactamente lo que quedó guardado (NIFs ya normalizados y
      // resueltos contra el maestro), así que una recarga solo repetiría la
      // misma respuesta y haría parpadear la tabla.
      queryClient.setQueryData(capacidadKeys.nifs(organizationId), data);
    },
  });
}

export function useOrganizationCapabilities(organizationId: number | null) {
  return useQuery({
    queryKey: capacidadKeys.capabilities(organizationId),
    queryFn: () =>
      fetchWithAuth<OrganizationCapabilities>(
        `/api/v1/organizations/${organizationId}/capabilities`,
      ),
    enabled: organizationId != null,
    staleTime: 30_000,
  });
}

export function useSaveOrganizationCapabilities(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OrganizationCapabilitiesIn) =>
      apiMutate<OrganizationCapabilities>(
        "PUT",
        `/api/v1/organizations/${organizationId}/capabilities`,
        body,
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(capacidadKeys.capabilities(organizationId), data);
    },
  });
}

/** Etiqueta en castellano de cada familia que el checklist puede echar en falta. */
export const CAMPO_LABELS: Record<OrganizationCapabilityField, string> = {
  certificaciones: "Certificaciones",
  facturacion: "Facturación anual",
  referencias: "Referencias de contratos",
  perfiles_equipo: "Perfiles de equipo",
};
