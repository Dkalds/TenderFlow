"use client";

/**
 * F4.3 — cartera de contratos en ejecución de la organización activa.
 *
 * Lleva `organization_id` siempre que haya una activa: sin él, el backend
 * resuelve la organización **personal**, y la cartera vive en la del equipo
 * (el mismo fallo que tuvo Dirección). Por eso tampoco sale antes de saber
 * cuál es la activa: la petición adelantada traía justo esa cartera vacía.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate, fetchWithAuth } from "@/lib/api-client";
import { primeraVez, registrarEvento } from "@/lib/analytics";
import type { RenovacionPreparada, Schemas } from "@/lib/api-types";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { pursuitKeys } from "@/lib/query-keys";

export type { RenovacionPreparada };
export type CarteraResumen = Schemas["CarteraResumen"];
export type ContratoEvento = Schemas["ContratoEvento"];

export function useCartera() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.cartera(organizationId),
    queryFn: () =>
      apiGet("/api/v1/pursuits/cartera", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    staleTime: 60_000,
  });
}

/**
 * Los totales de la cartera (`GET /pursuits/cartera/resumen`).
 *
 * Petición aparte y no una suma de las filas de `useCartera`: los agregados se
 * calculan en backend sobre el universo completo (ADR-014, invariante 1 de
 * `web/AGENTS.md`). «Vivos» o «vencen en seis meses» sumados en cliente
 * cambiarían en cuanto la tabla se recorte por un filtro, y la franja de KPIs
 * habla de la cartera entera, no de lo que se está mirando.
 *
 * Mismo tratamiento del ámbito que `useCartera`: sin organización resuelta no
 * sale, porque preguntar antes de saberla es preguntar por la personal.
 */
export function useCarteraResumen() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.carteraResumen(organizationId),
    queryFn: () =>
      apiGet("/api/v1/pursuits/cartera/resumen", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    staleTime: 60_000,
  });
}

/**
 * La cronología del contrato de una entrada de cartera
 * (`GET /pursuits/cartera/{id}/eventos`): qué le pasó después de ganarlo.
 *
 * Va por `fetchWithAuth` y no por `apiGet` porque la ruta lleva parámetro de
 * path y aquél sólo tipa rutas estáticas; el tipo de retorno sale igualmente
 * del esquema generado (`ContratoEvento`), nunca de una interfaz local.
 *
 * `carteraId === null` significa «no hay contrato seleccionado» y deja la
 * consulta parada: es el detalle del inspector, así que sólo se pide el del
 * contrato que se está mirando.
 */
export function useCarteraEventos(carteraId: number | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.carteraEventos(carteraId ?? "", organizationId),
    queryFn: () => {
      const query = organizationId != null ? `?organization_id=${organizationId}` : "";
      return fetchWithAuth<ContratoEvento[]>(
        `/api/v1/pursuits/cartera/${carteraId}/eventos${query}`,
      );
    },
    enabled: carteraId != null && organizacionResuelta(organizationId),
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
      // su enlace y la oportunidad nueva aparece en el tablero de Oportunidades
      // y en la Agenda.
      return queryClient.invalidateQueries({ queryKey: pursuitKeys.all });
    },
  });
}
