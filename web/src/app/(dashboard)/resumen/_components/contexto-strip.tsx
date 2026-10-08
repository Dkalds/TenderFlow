"use client";

import { PanelError, PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters, useScopedHref } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { AnalyticsOverview, ResumenHoyResult } from "@/lib/api-types";
import { useDesdeResumen, useRitmoDiario } from "../_hooks/use-publicaciones";
import { ComposicionPanel } from "./composicion-panel";
import { Sparkline } from "./contexto-graficos";

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
 * - **Activas** — cuánto hay abierto en el ámbito, y enlace al listado.
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
 * Bajo «Publicadas 30 d» va la línea del ritmo diario, la misma serie que el
 * panel de publicaciones (`useRitmoDiario`), y solo cuando el ámbito no mueve
 * las fechas: con otra ventana, la línea dibujaría otros días que la cifra.
 * La composición por estado vive en la misma sección, debajo: las dos son la
 * foto del ámbito.
 */
export function ContextoStrip() {
  const scopedHref = useScopedHref();
  const { rango } = useFilters();
  const ritmo = useRitmoDiario(useDesdeResumen());
  const ventanaPorDefecto = rango.desde == null && rango.hasta == null;
  const serie =
    ventanaPorDefecto && !ritmo.data?.serie_truncada ? (ritmo.data?.series ?? []).map((punto) => punto.count) : [];
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

  return (
    <section aria-labelledby="resumen-contexto" className="mb-5.5">
      <PanelTitle as="h2" id="resumen-contexto" title="Contexto de mercado" hint="del ámbito" className="mb-2.5" />
      {overview.error ? (
        <PanelError
          title="No se pudo cargar el contexto"
          error={overview.error}
          onRetry={() => void overview.refetch()}
        />
      ) : (
        <StatStrip columns={3}>
          <StatCell
            label="Activas"
            loading={hoy.isLoading}
            value={formatNumber(hoy.data?.total_activas)}
            href={scopedHref("/detalle?solo_abiertas=true")}
            hint="sin adjudicar ni cerrar"
          />
          <StatCell
            label="Publicadas 30 d"
            loading={loading}
            value={formatNumber(data?.licitaciones_30d)}
            trend={data?.yoy_delta}
            hint={
              <span className="flex items-center gap-2">
                <span className="flex-none">vs los 30 días previos</span>
                {serie.length > 1 && <Sparkline valores={serie} className="min-w-0 flex-1" />}
              </span>
            }
          />
          <StatCell
            label="Importe 30 d"
            loading={loading}
            value={formatCompactCurrency(data?.importe_30d)}
            hint="publicado en los últimos 30 días"
          />
        </StatStrip>
      )}
      <ComposicionPanel className="mt-2.5" />
    </section>
  );
}
