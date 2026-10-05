"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type {
  HistoricalDistribution,
  PriceScenario,
  PriceScenariosResult,
} from "@/lib/api-types";
import { prediccionKeys } from "@/lib/query-keys";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

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
 * `options.competencia` acota la cohorte a adjudicaciones con un número de
 * ofertas parecido (`competencia_esperada`, bandas 1 / 2-4 / 5+): es la
 * competencia esperada de la ficha, que el panel ofrece usar. Va también como
 * sufijo de la clave, y solo cuando se usa: sin ella la clave es la de siempre.
 *
 * `options.enabled` deja aplazar la llamada mientras el llamador todavía no
 * sabe si hay lote: pedir primero el del expediente y corregir después sería
 * enseñar un precio equivocado y cambiarlo delante del usuario.
 */
export function usePriceScenarios(
  licitacionId: string | null,
  loteId?: number | null,
  options?: { enabled?: boolean; competencia?: number | null },
) {
  const lote = loteId ?? null;
  const competencia = options?.competencia ?? null;
  const base = [...prediccionKeys.escenarios(licitacionId), lote] as const;
  const parametros = new URLSearchParams();
  if (lote != null) parametros.set("lote_id", String(lote));
  if (competencia != null) parametros.set("competencia_esperada", String(competencia));
  const query = parametros.toString();
  return useQuery({
    queryKey: competencia == null ? base : [...base, competencia],
    queryFn: () =>
      fetchWithAuth<PriceScenariosResult>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/escenarios-precio` +
          (query ? `?${query}` : ""),
      ),
    enabled: Boolean(licitacionId) && (options?.enabled ?? true),
    staleTime: 5 * 60_000,
    // Al acotar o soltar la competencia los escenarios anteriores siguen a la
    // vista mientras llegan los nuevos, pero solo si son del mismo expediente y
    // del mismo lote: un precio de otro objeto no se enseña ni un instante.
    placeholderData: (anterior, consultaAnterior) =>
      consultaAnterior?.queryKey[1] === licitacionId && consultaAnterior?.queryKey[2] === lote
        ? anterior
        : undefined,
    meta: META_ERROR_EN_LINEA,
  });
}
