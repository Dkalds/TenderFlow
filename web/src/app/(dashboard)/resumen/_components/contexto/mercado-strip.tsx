"use client";

/**
 * Contexto de mercado — las seis magnitudes del ámbito activo.
 *
 * Dos decisiones viven en esta tira y en ninguna otra:
 *
 * 1. **Los deltas van entre meses cerrados** y el pie dice cuáles («jul vs
 *    jun»), no un genérico «vs mes previo».
 * 2. **`yoy_delta` cuelga de «Publicadas 30 d»**, que es lo que mide: el
 *    backend lo calcula como `(licitaciones últimos 30 d − 30 d previos) /
 *    30 d previos`. Iba pegado al recuento de órganos con el rótulo «YoY» —
 *    métrica, periodo y etiqueta equivocados en el mismo número de 11 px.
 *
 * El badge de anomalía es la única cifra derivada en cliente de toda la
 * pantalla, y va etiquetado como tal en su propio tooltip — la salida que el
 * invariante 1 de `frontend-data-invariants.md` permite.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";
import type { ComparativaMensual } from "./comparativa-mensual";
import { STRIP_LG } from "./tiras";

function BadgeAnomalia({ meses }: { meses: number }) {
  return (
    <span
      title={`El último mes cerrado se aleja 2σ o más de la media de los ${meses} meses anteriores del ámbito. Señal calculada en el navegador sobre la serie mensual, no un dato del backend.`}
      className="inline-flex h-4 flex-none items-center rounded border border-[hsl(var(--warning)/0.38)] bg-[hsl(var(--warning)/0.14)] px-1 font-mono text-[8.5px] font-semibold tracking-[0.04em] text-[hsl(var(--warning))]"
    >
      ANOMALÍA
    </span>
  );
}

export interface MercadoStripProps {
  data: AnalyticsOverview | undefined;
  loading: boolean;
  comparativa: ComparativaMensual;
  /** Meses cerrados que sirven de historia al badge; sólo redacta su tooltip. */
  historial: number;
}

export function MercadoStrip({ data, loading, comparativa, historial }: MercadoStripProps) {
  const pieDelta = comparativa.etiqueta || "sin dos meses cerrados que comparar";

  return (
    <section aria-labelledby="resumen-contexto" className="mb-5.5">
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id="resumen-contexto" className="text-xs font-semibold">
          Contexto de mercado
        </h2>
        <span className="text-muted-foreground text-[10.5px]">
          del ámbito activo · deltas entre meses cerrados
        </span>
      </div>
      <StatStrip columns={6} className={STRIP_LG}>
        <StatCell
          label="Total licitaciones"
          loading={loading}
          value={formatNumber(data?.total_licitaciones)}
          trend={comparativa.count}
          hint={pieDelta}
          badge={comparativa.anomaliaCount ? <BadgeAnomalia meses={historial} /> : undefined}
        />
        <StatCell
          label="Importe total"
          loading={loading}
          value={formatCompactCurrency(data?.importe_total)}
          trend={comparativa.importe}
          hint={pieDelta}
          badge={comparativa.anomaliaImporte ? <BadgeAnomalia meses={historial} /> : undefined}
        />
        <StatCell
          label="Importe medio"
          loading={loading}
          value={formatCompactCurrency(data?.importe_medio)}
          trend={comparativa.medio}
          hint={pieDelta}
        />
        <StatCell
          label="Órganos únicos"
          loading={loading}
          value={formatNumber(data?.organos_unicos)}
          hint="convocantes distintos en el ámbito"
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
    </section>
  );
}
