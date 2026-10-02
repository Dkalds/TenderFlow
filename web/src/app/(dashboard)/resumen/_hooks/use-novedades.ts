"use client";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import type { ResumenNovedadesResult } from "@/lib/api-types";

/**
 * Licitaciones publicadas desde tu última visita, en el ámbito de la barra
 * (`GET /analytics/resumen/novedades`).
 *
 * El Resumen tenía tres ideas de «nuevo»: la tarjeta «Nuevas 24h», una línea
 * de «N nuevas desde tu última visita» encima de la tabla —de todo el mercado,
 * sin el ámbito— y la banda de lo que sigues. Ahora hay una sola para el
 * mercado: **desde tu última visita**, la misma marca y la misma fecha que la
 * banda de arriba, y **dentro del ámbito**, como el resto de «Mercado
 * abierto». La consumen dos sitios, que comparten clave y por tanto petición:
 *
 * - la tarjeta «Nuevas» de `atencion-cards.tsx`, que enseña la cifra;
 * - la tabla de `timeline-section.tsx`, que marca con un punto cada fila
 *   publicada después del corte `desde`.
 *
 * La clave empieza por `analyticsKeys.novedades`, que es lo que invalida
 * «Marcar todo como visto» (`desde-ultima-visita.tsx`). Sin `placeholderData`
 * (`isRealtime`): con el valor del ámbito anterior en pantalla mientras llega
 * el nuevo, la cifra mentiría durante la carga.
 */
export function useNovedades() {
  return useFilteredQuery<ResumenNovedadesResult>(
    ["analytics", "resumen", "novedades"],
    "/api/v1/analytics/resumen/novedades",
    // El fallo se dice en la tarjeta: sin toast encima.
    { staleTime: 60_000, meta: META_ERROR_EN_LINEA },
    undefined,
    true,
  );
}
