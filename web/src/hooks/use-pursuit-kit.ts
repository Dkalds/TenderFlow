"use client";

/**
 * F2.3 — kit de presentación de una oportunidad.
 *
 * Las tres operaciones devuelven el kit **entero**: el checklist es
 * colaborativo, y la respuesta de un marcado trae también lo que otros han
 * marcado o asignado desde que se cargó. Por eso las mutaciones siembran la
 * caché con la respuesta en vez de invalidar y volver a pedir.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import {
  organizacionResuelta,
  useActiveOrganizationId,
  type OrganizacionActiva,
} from "@/hooks/use-organization";
import { pursuitKeys } from "@/lib/query-keys";
import { registrarEvento, tramoDeItems } from "@/lib/analytics";

export type KitPresentacion = Schemas["KitPresentacion"];
export type ItemKit = Schemas["ItemKit"];

function kitUrl(pursuitId: number, organizationId: OrganizacionActiva, sufijo = ""): string {
  const query = organizationId != null ? `?organization_id=${organizationId}` : "";
  return `/api/v1/pursuits/${encodeURIComponent(String(pursuitId))}/kit${sufijo}${query}`;
}

export function usePursuitKit(pursuitId: number) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.kit(pursuitId, organizationId),
    queryFn: () => fetchWithAuth<KitPresentacion>(kitUrl(pursuitId, organizationId)),
    // El kit es de un expediente de la organización activa: pedirlo antes de
    // saber cuál es lo busca en la personal y responde 404.
    enabled: organizacionResuelta(organizationId),
    staleTime: 30_000,
  });
}

/**
 * Adopción: ¿se abre el kit, y con cuántos documentos? Una vez por montaje y
 * no en la `queryFn`: cada refetch en segundo plano contaría como una apertura.
 * En tramos: el tamaño exacto no aporta, y un kit vacío es un fallo de
 * extracción que hay que poder ver.
 */
export function registrarKitAbierto(kit: KitPresentacion): void {
  registrarEvento("kit_abierto", { items: tramoDeItems(kit.items?.length ?? 0) });
}

/** Documentos listos / total, por sobre. Función pura para poder probarla. */
export function resumenKit(kit: KitPresentacion | undefined): { listos: number; total: number } {
  const items = kit?.items ?? [];
  return { listos: items.filter((item) => item.listo).length, total: items.length };
}

export function useMarcarKitItem(pursuitId: number) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (input: Schemas["KitItemBody"]) =>
      apiMutate<KitPresentacion>("POST", kitUrl(pursuitId, organizationId), input),
    onSuccess: (kit) => {
      queryClient.setQueryData(pursuitKeys.kit(pursuitId, organizationId), kit);
    },
  });
}

export function useAsignarKitItem(pursuitId: number) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (input: Schemas["KitResponsableBody"]) =>
      apiMutate<KitPresentacion>("POST", kitUrl(pursuitId, organizationId, "/responsable"), input),
    onSuccess: (kit) => {
      queryClient.setQueryData(pursuitKeys.kit(pursuitId, organizationId), kit);
      // Asignar crea (o reasigna) una tarea, y la tarea mueve la próxima
      // acción de la oportunidad: el tablero y la agenda la leen.
      void queryClient.invalidateQueries({ queryKey: pursuitKeys.detail(String(pursuitId)) });
      void queryClient.invalidateQueries({ queryKey: pursuitKeys.agenda });
    },
  });
}
