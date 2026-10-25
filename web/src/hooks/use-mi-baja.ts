"use client";

/**
 * «Mi baja frente al mercado» (`GET /pursuits/mi-baja`, C6.5).
 *
 * La baja media de las ofertas que la organización presentó, por CPV de cuatro
 * dígitos y por órgano, junto a la baja ganadora media del mercado en ese
 * mismo segmento. La calcula entera el backend (`services/mi_baja.py`): aquí
 * no se agrega ni se recalcula nada (ADR-014).
 */

import { useQuery } from "@tanstack/react-query";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { pursuitKeys } from "@/lib/query-keys";

export type MiBajaSegmento = Schemas["MiBajaSegmento"];

export function useMiBaja() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.miBaja(organizationId),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/pursuits/mi-baja", {
        params: { query: { organization_id: organizationId ?? undefined } },
        signal,
      }),
    // Mismo motivo que el tablero: preguntar antes de saber la organización
    // sería preguntar por la personal.
    enabled: organizacionResuelta(organizationId),
    // Cambia cuando se presenta una oferta, no de un minuto a otro; y cada
    // segmento es una consulta agregada sobre adjudicaciones.
    staleTime: 10 * 60_000,
    meta: META_ERROR_EN_LINEA,
  });
}
