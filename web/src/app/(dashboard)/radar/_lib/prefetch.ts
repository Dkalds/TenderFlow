import { radarKeys } from "@/lib/query-keys";
import type { ConsultaServidor } from "@/lib/server-prefetch";

/**
 * Cuántas filas se piden a `GET /radar/proximas`. Cabe la bandeja entera con
 * holgura: la medición del spike
 * (`docs/plans/2026-09-spike-planes-anuales-placsp.md`) dice que `PRE` es el
 * 0,14 % del flujo de PLACSP y que `CPM` no entra por ahí. Si algún día el
 * `total` supera este tope, la cabecera lo dirá comparando `total` con las
 * filas recibidas en vez de callarlo.
 *
 * Vive fuera del hook (`_hooks/use-radar-proximas.ts`, `"use client"`) porque
 * el prefetch en servidor necesita el mismo número para construir la misma
 * clave: una constante exportada desde un módulo cliente llega al servidor
 * como referencia, no como valor.
 */
export const LIMITE_PROXIMAS = 100;

/**
 * Lo que `radar/layout.tsx` pide en servidor: las consultas del Radar que **no**
 * dependen de la organización activa (ver `lib/server-prefetch.ts`, regla 2).
 * El ranking (`GET /analytics/scoring`) sí depende de ella y se queda en el
 * cliente. Tampoco dependen de la URL, y por eso el prefetch puede vivir en el
 * layout de la ruta y no en `page.tsx`.
 *
 * Cada `transformar` replica el `queryFn` de su hook: `useRadarDismissals`
 * cachea `response.ids`, no la respuesta entera.
 */
export function consultasRadar(): ConsultaServidor[] {
  return [
    {
      queryKey: radarKeys.dismissals,
      path: "/api/v1/radar/dismissals",
      transformar: (cuerpo) => (cuerpo as { ids: string[] }).ids,
    },
    {
      queryKey: radarKeys.proximas(LIMITE_PROXIMAS),
      path: `/api/v1/radar/proximas?limit=${LIMITE_PROXIMAS}`,
    },
  ];
}
