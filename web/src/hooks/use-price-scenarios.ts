"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type {
  HistoricalDistribution,
  PriceScenario,
  PriceScenariosResult,
} from "@/lib/api-types";
import { prediccionKeys } from "@/lib/query-keys";

export type { HistoricalDistribution, PriceScenario, PriceScenariosResult };

/**
 * Escenarios de precio del expediente o —con `loteId`— de uno de sus lotes.
 *
 * El lote es la unidad sobre la que se puja de verdad (S3.1): con `loteId` el
 * backend calcula los tres precios sobre el presupuesto de ese lote y no sobre
 * el del expediente, que es lo que hacía que la ficha de una oportunidad por
 * lote enseñara cifras de un objeto de contrato que nadie iba a firmar.
 *
 * El lote se añade como sufijo de la clave de caché **aquí** y no en
 * `query-keys.ts`: `prediccionKeys.escenarios` es la clave del expediente y
 * sigue siendo su prefijo (las invalidaciones por prefijo siguen alcanzando a
 * las dos variantes), pero sin sufijo el escenario del lote 2 y el del
 * expediente compartirían entrada y se pisarían.
 *
 * `options.enabled` deja aplazar la llamada mientras el llamador todavía no
 * sabe si hay lote: pedir primero el del expediente y corregir después sería
 * enseñar un precio equivocado y cambiarlo delante del usuario.
 */
export function usePriceScenarios(
  licitacionId: string | null,
  loteId?: number | null,
  options?: { enabled?: boolean },
) {
  const lote = loteId ?? null;
  return useQuery({
    queryKey: [...prediccionKeys.escenarios(licitacionId), lote],
    queryFn: () =>
      fetchWithAuth<PriceScenariosResult>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/escenarios-precio` +
          (lote == null ? "" : `?lote_id=${lote}`),
      ),
    enabled: Boolean(licitacionId) && (options?.enabled ?? true),
    staleTime: 5 * 60_000,
  });
}
