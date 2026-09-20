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
import type { OrganizationSettings, OrganizationSettingsOut } from "@/lib/api-types";
import { organizationKeys, pursuitKeys, radarKeys } from "@/lib/query-keys";

/** Alias histórico; la fábrica canónica es `organizationKeys` de `lib/query-keys`. */
export const organizationSettingsKeys = {
  detail: organizationKeys.settings,
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

/**
 * El cuerpo del PUT: la configuración guardada con el cambio encima.
 *
 * El backend **escribe el cuerpo entero** (`services/organizations.py::
 * update_settings`: «se escribe el cuerpo entero, no sólo `tecnologias`»), y
 * el DTO declara el ámbito de mercado (F6.1) y las probabilidades por etapa
 * (F4.1). Mandar sólo la clave que se edita devolvía 200 y dejaba el resto a
 * sus valores vacíos: guardar las tecnologías borraba en silencio las
 * probabilidades, y al revés. Aquí se parte de lo guardado y se quitan las
 * claves de solo lectura de la respuesta (`extra="forbid"` las rechazaría).
 */
export function cuerpoDeAjustes(
  guardados: OrganizationSettingsOut,
  cambio: Partial<OrganizationSettings>,
): OrganizationSettings {
  const {
    organization_id: _organizacion,
    tecnologias_disponibles: _disponibles,
    probabilidades_etapa_default: _defaults,
    ...ajustes
  } = guardados;
  return { ...ajustes, ...cambio };
}

export function useUpdateOrganizationSettings(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (cambio: Partial<OrganizationSettings>) => {
      const url = `/api/v1/organizations/${organizationId}/settings`;
      // Lo guardado sale de la caché de la pantalla; si no está (nadie la ha
      // pintado), se pide: sin ello el PUT borraría lo que no se ve.
      const guardados =
        queryClient.getQueryData<OrganizationSettingsOut>(
          organizationSettingsKeys.detail(organizationId),
        ) ?? (await fetchWithAuth<OrganizationSettingsOut>(url));
      return apiMutate<OrganizationSettingsOut>("PUT", url, cuerpoDeAjustes(guardados, cambio));
    },
    onSuccess: (settings) => {
      queryClient.setQueryData(organizationSettingsKeys.detail(organizationId), settings);
      // El Radar acota su universo con estas familias y el valor ponderado del
      // pipeline usa las probabilidades por etapa: las dos cachés dejan de ser
      // válidas aquí y no en el siguiente refetch por tiempo.
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: organizationKeys.all }),
        queryClient.invalidateQueries({ queryKey: radarKeys.scoring }),
        queryClient.invalidateQueries({ queryKey: pursuitKeys.metrics }),
      ]);
    },
  });
}
