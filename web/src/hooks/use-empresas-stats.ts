/**
 * Cobertura de la resolución de entidades: cuánto de lo adjudicado está
 * atribuido a una empresa del maestro (`GET /api/v1/empresas/stats`).
 *
 * La leen dos pantallas. En Empresas es donde se arregla, con la cola de
 * revisión y el backfill. En Competencia es donde se nota, en sus cuotas. Hasta
 * 2026-09-25 la consulta y el umbral vivían en la página de Empresas, y quien
 * leía las cuotas no se enteraba de que podían estar mal.
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { empresasKeys } from "@/lib/query-keys";

export type EmpresasStats = Schemas["EmpresasStats"];

/**
 * Porcentaje del importe adjudicado que tiene que estar resuelto para fiarse
 * de las cuotas de Competencia. Por debajo, una misma empresa puede quedar
 * repartida entre varias filas (Competencia sólo junta lo que no está en el
 * maestro si coincide el NIF o el nombre normalizado).
 */
export const UMBRAL_IMPORTE_RESUELTO = 95;

export function useEmpresasStats() {
  return useQuery<EmpresasStats>({
    queryKey: empresasKeys.stats,
    queryFn: () => fetchWithAuth<EmpresasStats>("/api/v1/empresas/stats"),
    staleTime: 5 * 60 * 1000,
  });
}

/** ¿La cobertura está medida y por debajo del umbral? Sin dato, no se avisa. */
export function importeResueltoBajoUmbral(stats: EmpresasStats | undefined): boolean {
  return stats != null && stats.pct_importe < UMBRAL_IMPORTE_RESUELTO;
}
