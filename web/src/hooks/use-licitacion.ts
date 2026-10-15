"use client";

/**
 * El expediente completo, por id.
 *
 * Existe porque la ficha de una oportunidad y el inspector de Detalle son la
 * misma licitación vista desde dos sitios: hasta 2026-09 el contenido del
 * expediente sólo vivía en `/detalle` y la oportunidad —donde se decide— sólo
 * enlazaba a él. Quien decidía miraba una pantalla y leía la otra.
 *
 * El tipo sale del esquema generado, no se copia a mano: un campo que la API
 * deje de enviar rompe el typecheck aquí y no la pantalla.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { LicitacionDetail, SimilaresResult } from "@/lib/api-types";
import { licitacionKeys } from "@/lib/query-keys";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export { licitacionKeys } from "@/lib/query-keys";

export function useLicitacion(id: string | null) {
  return useQuery({
    queryKey: licitacionKeys.detail(id ?? ""),
    queryFn: () =>
      fetchWithAuth<LicitacionDetail>(`/api/v1/licitaciones/${encodeURIComponent(id!)}`),
    enabled: Boolean(id),
    // El expediente cambia con la pasada de ingesta (cada 4 h), no entre
    // pestañas: revalidar en cada foco sería tráfico sin información nueva.
    staleTime: 5 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Expedientes parecidos a este (`GET /licitaciones/{id}/similares`, C1.3).
 *
 * Existía sin ningún consumidor. La respuesta trae también el predecesor, pero
 * ése ya lo enseña la competencia esperada como incumbente; aquí se usan los
 * parecidos, con el `metodo` y el `n` que dicen cómo leerlos.
 */
export function useSimilares(id: string | null, limite = 5) {
  return useQuery({
    queryKey: licitacionKeys.similares(id ?? "", limite),
    queryFn: ({ signal }) =>
      fetchWithAuth<SimilaresResult>(
        `/api/v1/licitaciones/${encodeURIComponent(id!)}/similares?limit=${limite}`,
        { signal },
      ),
    enabled: Boolean(id),
    staleTime: 5 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}
