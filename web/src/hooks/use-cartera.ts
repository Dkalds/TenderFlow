"use client";

/**
 * F4.3 — cartera de contratos en ejecución de la organización activa.
 *
 * Lleva `organization_id` siempre que haya una activa: sin él, el backend
 * resuelve la organización **personal**, y la cartera vive en la del equipo
 * (el mismo fallo que tuvo Dirección).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";
import { primeraVez, registrarEvento } from "@/lib/analytics";
import type { RenovacionPreparada } from "@/lib/api-types";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { pursuitKeys } from "@/lib/query-keys";

export type { RenovacionPreparada };

export function useCartera() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.cartera(organizationId),
    queryFn: () =>
      apiGet("/api/v1/pursuits/cartera", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    staleTime: 60_000,
  });
}

/**
 * «Preparar renovación»: crea la oportunidad de la relicitación, enlazada al
 * contrato. Idempotente en el backend —un segundo clic devuelve la misma con
 * `creada=false`—, así que el evento de activación solo se cuenta cuando de
 * verdad nació una oportunidad.
 */
export function usePrepararRenovacion() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({ carteraId, licitacionId }: { carteraId: number; licitacionId: string }) => {
      const ruta = `/api/v1/pursuits/cartera/${carteraId}/renovacion`;
      return apiMutate<RenovacionPreparada>(
        "POST",
        organizationId != null ? `${ruta}?organization_id=${organizationId}` : ruta,
        { licitacion_id: licitacionId },
      );
    },
    onSuccess: (resultado) => {
      if (resultado.creada) {
        registrarEvento("pursuit_creado", { primera_vez: primeraVez("pursuit"), origen: "renovacion" });
      }
      // `pursuitKeys.all` es prefijo de la cartera y del tablero: la fila gana
      // su enlace y la oportunidad nueva aparece en Mi Pipeline.
      return queryClient.invalidateQueries({ queryKey: pursuitKeys.all });
    },
  });
}
