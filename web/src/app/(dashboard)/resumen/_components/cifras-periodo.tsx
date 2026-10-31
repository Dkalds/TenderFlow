"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { ROTULO_DATO } from "@/components/console/panel";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, EMPTY, formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";

/**
 * Las cifras del periodo — lo publicado en 30 días y lo que se puso en juego.
 *
 * Era una tira de siete magnitudes y otra de seis indicadores de competencia:
 * total de licitaciones, importe total y medio, órganos únicos, HHI, oferta
 * única, días hasta adjudicar… Una radiografía del mercado en la pantalla cuyo
 * trabajo es decir qué hay que hacer hoy. Esas magnitudes viven en Mercado y
 * en Competencia, que es donde se analizan; aquí queda lo que sitúa el mes:
 *
 * - **Publicadas 30 d**, con su variación contra los 30 días previos
 *   (`yoy_delta`, que el backend calcula así pese al nombre).
 * - **Importe 30 d** — lo que se ha puesto en juego en ese mismo mes.
 *
 * **Dentro del panel de publicaciones** (2026-10-31, el diseño aprobado del
 * Resumen compacto): son el resumen en cifras del gráfico que tienen debajo,
 * y como tira propia encima del panel alargaban su columna hasta dejar un
 * hueco bajo la composición y el mapa. «Activas», la tercera cifra que
 * llevaba, subió a la tira del mercado de hoy (`atencion-cards.tsx`).
 *
 * Misma clave y mismas opciones que `composicion-panel.tsx` para
 * `/analytics/overview`: React Query la sirve de una sola petición, y el
 * prefetch en servidor (`_lib/prefetch.ts`) la hidrata. El fallo lo pinta la
 * composición; aquí las cifras quedan en raya.
 */
export function CifrasPeriodo({ className }: { className?: string }) {
  const overview = useFilteredQuery<AnalyticsOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );
  const data = overview.data;
  const delta = data?.yoy_delta;

  return (
    <dl className={cn("flex flex-wrap gap-x-6 gap-y-2", className)}>
      <div className="min-w-0">
        <dt className={ROTULO_DATO}>Publicadas 30 d</dt>
        <dd className="flex items-baseline gap-2">
          {overview.isLoading ? (
            <Skeleton className="h-6 w-20 rounded-sm" />
          ) : (
            <span className="tf-tnum text-tf-title font-semibold">
              {data ? formatNumber(data.licitaciones_30d) : EMPTY}
            </span>
          )}
          {delta != null && (
            <span
              className={cn(
                "tf-tnum text-tf-meta font-medium",
                delta >= 0 ? "text-success" : "text-destructive",
              )}
            >
              {delta >= 0 ? "+" : ""}
              {formatPercent(delta)}
              <span className="sr-only"> frente a los 30 días previos</span>
            </span>
          )}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className={ROTULO_DATO}>Importe 30 d</dt>
        <dd>
          {overview.isLoading ? (
            <Skeleton className="h-6 w-20 rounded-sm" />
          ) : (
            <span className="tf-tnum text-tf-title font-semibold">
              {data ? formatCompactCurrency(data.importe_30d) : EMPTY}
            </span>
          )}
        </dd>
      </div>
    </dl>
  );
}
