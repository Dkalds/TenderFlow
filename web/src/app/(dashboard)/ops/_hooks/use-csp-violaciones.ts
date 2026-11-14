"use client";

/**
 * Violaciones de la política CSP, agrupadas por directiva y origen
 * (`GET /security/csp-violations`). Ruta de administrador: quien la pinta solo
 * se monta para administradores.
 */

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";

const LIMITE = 20;

export function useCspViolaciones() {
  return useQuery({
    queryKey: adminKeys.cspViolations,
    queryFn: () =>
      apiGet("/api/v1/security/csp-violations", { params: { query: { limit: LIMITE } } }),
    staleTime: 60_000,
    // El fallo lo dice el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
