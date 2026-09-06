"use client";

/**
 * Invitaciones pendientes de una organización.
 *
 * Vive aquí y no en `hooks/use-organization.ts` porque solo lo consume
 * `/equipo`: es la pantalla donde se invita, se reenvía y se revoca. Los tipos
 * salen del cliente generado (`Schemas[...]`), no de una forma escrita a mano.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { organizationKeys } from "@/lib/query-keys";

export type OrganizationInvitation = Schemas["OrganizationInvitationOut"];

/** Clave de caché propia: `organizationKeys` no la declara y no es su fichero. */
export const invitationKeys = {
  list: (organizationId: number | null) =>
    [...organizationKeys.members(organizationId), "invitations"] as const,
};

export function useOrganizationInvitations(organizationId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: invitationKeys.list(organizationId),
    queryFn: () =>
      fetchWithAuth<OrganizationInvitation[]>(
        `/api/v1/organizations/${organizationId}/invitations`,
      ),
    select: (invitations) => (Array.isArray(invitations) ? invitations : []),
    // Solo owner/admin pueden leerlas: pedirlas como `member` daría un 403 en
    // cada carga de la pantalla, ruido sin ninguna información nueva.
    enabled: organizationId != null && enabled,
    staleTime: 30_000,
  });
}

/**
 * Invalida a la vez miembros e invitaciones.
 *
 * Las dos listas cambian con la misma acción: al aceptarse una invitación, la
 * fila desaparece de una y aparece en la otra. Refrescar solo una dejaba la
 * pantalla mostrando a la misma persona dos veces.
 */
function useInvalidateTeam(organizationId: number | null) {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: organizationKeys.members(organizationId) }),
      queryClient.invalidateQueries({ queryKey: invitationKeys.list(organizationId) }),
    ]);
  };
}

export function useResendInvitation(organizationId: number | null) {
  const invalidate = useInvalidateTeam(organizationId);
  return useMutation({
    mutationFn: (invitationId: number) =>
      apiMutate<OrganizationInvitation>(
        "POST",
        `/api/v1/organizations/${organizationId}/invitations/${invitationId}/resend`,
      ),
    onSuccess: invalidate,
  });
}

export function useRevokeInvitation(organizationId: number | null) {
  const invalidate = useInvalidateTeam(organizationId);
  return useMutation({
    mutationFn: (invitationId: number) =>
      apiMutate<{ status: string }>(
        "DELETE",
        `/api/v1/organizations/${organizationId}/invitations/${invitationId}`,
      ),
    onSuccess: invalidate,
  });
}
