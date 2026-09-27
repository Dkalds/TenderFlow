"use client";

/**
 * Contexto de mercado — las siete magnitudes del ámbito activo.
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
 * pantalla, y va etiquetado como tal en su propio tooltip («aviso
 * orientativo») — la salida que el invariante 1 de
 * `frontend-data-invariants.md` permite.
 */

import { PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { badgeVariants } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";
import { AvisoAlcance } from "../aviso-alcance";
import type { ComparativaMensual } from "./comparativa-mensual";

/**
 * «Anomalía», con su explicación a un tooltip. El disparador es un botón de
 * verdad: un `span` con tooltip no se alcanza con el teclado, y aquí el
 * tooltip es lo que dice que la marca es orientativa.
 */
function BadgeAnomalia({ meses }: { meses: number }) {
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        className={cn(badgeVariants({ variant: "warning", size: "sm" }), "flex-none cursor-help")}
      >
        Anomalía
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        {`El último mes cerrado se sale de lo habitual: se aleja 2σ o más de la media de los ${meses} meses anteriores del ámbito. Es un aviso orientativo, no un dato oficial.`}
      </TooltipContent>
    </Tooltip>
  );
}

export interface MercadoStripProps {
  data: AnalyticsOverview | undefined;
  loading: boolean;
  comparativa: ComparativaMensual;
  /** Meses cerrados que sirven de historia al badge; sólo redacta su tooltip. */
  historial: number;
  /**
   * Expedientes activos del ámbito. Llega por props y no de una consulta
   * propia porque sale de `/resumen/hoy`, otro endpoint, y quien lo pide es el
   * orquestador — que ya comparte esa clave de React Query con
   * `atencion-cards.tsx` y así las dos se sirven de una sola petición.
   */
  activas: number | null | undefined;
  activasLoading: boolean;
  activasHref: string;
  /**
   * Filtros del ámbito que «Activas» no aplica (`useFiltrosIgnorados`): sale de
   * `/resumen/hoy`, que solo filtra por fecha, CCAA y tecnología, mientras sus
   * seis vecinas aplican el ámbito entero. Vacío = mide lo mismo que ellas.
   */
  activasIgnoran?: string[];
}

export function MercadoStrip({
  data,
  loading,
  comparativa,
  historial,
  activas,
  activasLoading,
  activasHref,
  activasIgnoran = [],
}: MercadoStripProps) {
  const pieDelta = comparativa.etiqueta || "sin dos meses cerrados que comparar";

  return (
    <section aria-labelledby="resumen-contexto" className="mb-5.5">
      <PanelTitle as="h2" id="resumen-contexto" title="Contexto de mercado" hint="del ámbito" className="mb-2.5" />
      <AvisoAlcance ignorados={activasIgnoran} sujeto="activas" />
      <StatStrip columns={7}>
        <StatCell
          label="Activas"
          loading={activasLoading}
          value={formatNumber(activas)}
          href={activasHref}
          hint="sin adjudicar ni cerrar"
        />
        <StatCell
          label="Total licitaciones"
          loading={loading}
          value={formatNumber(data?.total_licitaciones)}
          trend={comparativa.count}
          trendAlert={comparativa.anomaliaCount}
          hint={pieDelta}
          badge={comparativa.anomaliaCount ? <BadgeAnomalia meses={historial} /> : undefined}
        />
        <StatCell
          label="Importe total"
          loading={loading}
          value={formatCompactCurrency(data?.importe_total)}
          trend={comparativa.importe}
          trendAlert={comparativa.anomaliaImporte}
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
