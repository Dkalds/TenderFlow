"use client";

/**
 * Configuración de producto de la organización: qué familias tecnológicas
 * vende el equipo.
 *
 * El diccionario de familias (SAP, MICROSOFT, ORACLE…) vive en el backend y no
 * se copia aquí: `tecnologias_disponibles` viaja en la respuesta justo para
 * que el selector no mantenga una lista paralela que se desincronice cuando se
 * añada una familia nueva.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { OrganizationSettingsOut } from "@/lib/api-types";

export const organizationSettingsKeys = {
  detail: (organizationId: number | null) => ["organization-settings", organizationId] as const,
};

export function useOrganizationSettings(organizationId: number | null) {
  return useQuery({
    queryKey: organizationSettingsKeys.detail(organizationId),
    queryFn: () =>
      fetchWithAuth<OrganizationSettingsOut>(`/api/v1/organizations/${organizationId}/settings`),
    enabled: organizationId != null,
    staleTime: 60_000,
  });
}

export function useUpdateOrganizationSettings(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tecnologias: string[]) =>
      apiMutate<OrganizationSettingsOut>(
        "PUT",
        `/api/v1/organizations/${organizationId}/settings`,
        { tecnologias },
      ),
    onSuccess: (settings) => {
      queryClient.setQueryData(organizationSettingsKeys.detail(organizationId), settings);
      // El Radar acota su universo con estas familias: su ranking cambia en
      // cuanto se guardan, así que su caché deja de ser válida aquí y no en el
      // siguiente refetch por tiempo.
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: ["organizations"] }),
        queryClient.invalidateQueries({ queryKey: ["radar", "scoring"] }),
      ]);
    },
  });
}
