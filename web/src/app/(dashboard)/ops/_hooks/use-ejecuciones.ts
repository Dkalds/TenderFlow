"use client";

/**
 * Resumen de ejecuciones: los pasos del cierre post-ingesta y la cola de
 * trabajo a demanda (`GET /admin/ejecuciones`).
 *
 * Una sola consulta para tres consumidores —la vista, la celda de la tira de
 * salud y el contador de la pestaña—, así que los tres enseñan el mismo número
 * en el mismo instante. `enabled` existe porque la ruta es de administrador: la
 * tira se monta también para quien no lo es, y pedirla sería un 403 seguro.
 */

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";

export type EjecucionesResumen = Schemas["EjecucionesResumen"];
export type PasoEjecucion = Schemas["PasoEjecucion"];
export type TrabajoResumen = Schemas["TrabajoResumen"];

export function useEjecuciones({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: adminKeys.ejecuciones,
    queryFn: () => apiGet("/api/v1/admin/ejecuciones"),
    enabled,
    staleTime: 60_000,
    // La pasada corre cada cuatro horas: cinco minutos sobran para enterarse.
    refetchInterval: 5 * 60_000,
    // El fallo lo dice quien pinta el dato: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
