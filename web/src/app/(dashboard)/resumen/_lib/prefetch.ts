import { filteredQueryKey, filteredQueryUrl, mergeFilteredParams } from "@/lib/filtered-query";
import type { ConsultaServidor } from "@/lib/server-prefetch";

/**
 * Consultas con ámbito que el Resumen pide en servidor (`resumen/page.tsx`).
 *
 * Son las dos con ámbito que comparten varias bandas:
 * `/analytics/resumen/hoy` (la cola de cierre y la tira de «Mercado hoy») y
 * `/analytics/overview` (las activas del ámbito, el importe y lo publicado en
 * 30 días). Las dos dependen sólo del
 * ámbito de la URL, que el servidor lee igual que el navegador. «Tu día»
 * depende de la organización activa y se queda en el cliente (ver
 * `lib/server-prefetch.ts`, regla 2).
 *
 * La clave se construye con las mismas funciones que `useFilteredQuery`, y la
 * `baseKey` y la URL son las de `cifras-periodo.tsx` y `atencion-cards.tsx`:
 * si una de esas llamadas cambia, el test de
 * `resumen/_lib/__tests__/prefetch.test.tsx` deja de encontrar la clave.
 */
export const CONSULTAS_CON_AMBITO_RESUMEN = [
  { baseKey: ["analytics", "resumen", "hoy"], url: "/api/v1/analytics/resumen/hoy" },
  { baseKey: ["analytics", "overview"], url: "/api/v1/analytics/overview" },
] as const;

export function consultasResumen(filterParams: Record<string, string>): ConsultaServidor[] {
  const merged = mergeFilteredParams(filterParams);
  return CONSULTAS_CON_AMBITO_RESUMEN.map(({ baseKey, url }) => ({
    queryKey: filteredQueryKey(baseKey, url, merged),
    path: filteredQueryUrl(url, merged),
  }));
}
