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
import type { LicitacionDetail } from "@/lib/api-types";

export const licitacionKeys = {
  detail: (id: string) => ["licitacion", id] as const,
};

export function useLicitacion(id: string | null) {
  return useQuery({
    queryKey: licitacionKeys.detail(id ?? ""),
    queryFn: () =>
      fetchWithAuth<LicitacionDetail>(`/api/v1/licitaciones/${encodeURIComponent(id!)}`),
    enabled: Boolean(id),
    // El expediente cambia con la pasada de ingesta (cada 4 h), no entre
    // pestañas: revalidar en cada foco sería tráfico sin información nueva.
    staleTime: 5 * 60 * 1000,
  });
}
