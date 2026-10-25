"use client";

import { PanelError, StatCell, StatStrip } from "@/components/console/panel";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useScopedHref } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { AnalyticsOverview, ResumenHoyResult } from "@/lib/api-types";
import { Proporcion } from "./cifras-graficos";

/**
 * Contexto de mercado — tres cifras del ámbito, ninguna urgente.
 *
 * Era una tira de siete magnitudes y otra de seis indicadores de competencia:
 * total de licitaciones, importe total y medio, órganos únicos, HHI, oferta
 * única, días hasta adjudicar… Una radiografía del mercado en la pantalla cuyo
 * trabajo es decir qué hay que hacer hoy, y medio de ella global —sin tu
 * ámbito— en una pantalla llena de chips. Esas magnitudes viven en Mercado y en
 * Competencia, que es donde se analizan; aquí queda lo que sitúa el día:
 *
 * - **Activas** — cuánto hay abierto en el ámbito, y enlace al listado. Lleva
 *   su parte del ámbito en barra: `total_activas` sobre `total_licitaciones`,
 *   los dos sobre el mismo conjunto filtrado (ver abajo).
 * - **Publicadas 30 d**, con su variación contra los 30 días previos
 *   (`yoy_delta`, que el backend calcula así pese al nombre).
 * - **Importe 30 d** — lo que se ha puesto en juego en ese mismo mes.
 *
 * «Activas» sale de `/resumen/hoy` y las otras dos de `/analytics/overview`.
 * Los dos aplican el ámbito entero con la semántica del listado, así que las
 * tres celdas miden el mismo universo y la tira no tiene nada que avisar.
 * Misma clave y mismas opciones que `atencion-cards.tsx` para `/resumen/hoy` y
 * que `composicion-panel.tsx` para `/analytics/overview`: React Query sirve
 * cada una de una sola petición, y el prefetch en servidor
 * (`_lib/prefetch.ts`) las hidrata.
 *
 * **Sin rótulo ni dibujo propio.** La tira abre el grupo del periodo en
 * `resumen-view.tsx`, justo encima del ritmo de publicaciones y de los
 * movimientos: es su resumen en cifras. Bajo «Publicadas 30 d» e «Importe
 * 30 d» llevaba un área con la misma serie diaria que el gráfico de barras
 * pintaba un palmo más abajo, así que salió. La composición por estado y el
 * reparto por comunidad, que vivían en esta sección, son ahora un bloque
 * propio al final de la zona: son la foto del ámbito, no el pulso del mes.
 */
export function ContextoStrip() {
  const scopedHref = useScopedHref();
  // El fallo se pinta aquí (y en la composición, que lee la misma consulta):
  // sin toast encima.
  const overview = useFilteredQuery<AnalyticsOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );
  const hoy = useFilteredQuery<ResumenHoyResult>(
    ["analytics", "resumen", "hoy"],
    "/api/v1/analytics/resumen/hoy",
    { staleTime: 2 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    undefined,
    true,
  );

  const data = overview.data;
  const loading = overview.isLoading;

  if (overview.error) {
    return (
      <PanelError
        title="No se pudo cargar el contexto"
        error={overview.error}
        onRetry={() => void overview.refetch()}
      />
    );
  }

  // Tres cifras no caben en la rejilla de dos de un teléfono: la tercera
  // quedaba sola junto a un hueco gris. Una por fila hasta `sm`, y tres desde
  // ahí.
  return (
    <StatStrip columns={3} className="grid-cols-1 sm:grid-cols-3">
      <StatCell
        label="Activas"
        loading={hoy.isLoading}
        value={formatNumber(hoy.data?.total_activas)}
        href={scopedHref("/detalle?solo_abiertas=true")}
        grafico={
          hoy.data && data && data.total_licitaciones > 0 ? (
            <Proporcion parte={hoy.data.total_activas} total={data.total_licitaciones} de="del ámbito" />
          ) : undefined
        }
        hint="sin adjudicar ni cerrar"
      />
      <StatCell
        label="Publicadas 30 d"
        loading={loading}
        value={formatNumber(data?.licitaciones_30d)}
        trend={data?.yoy_delta}
        hint="vs los 30 días previos"
      />
      <StatCell
        label="Importe 30 d"
        loading={loading}
        value={formatCompactCurrency(data?.importe_30d)}
        hint="publicado en los últimos 30 días"
      />
    </StatStrip>
  );
}
