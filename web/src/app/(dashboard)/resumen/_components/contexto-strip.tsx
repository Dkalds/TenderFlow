"use client";

import { useMemo } from "react";
import { PanelError, StatCell, StatStrip } from "@/components/console/panel";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { isAnomaly } from "@/lib/anomaly-detection";
import {
  EMPTY,
  formatCompactCurrency,
  formatMonth,
  formatNumber,
  formatPercent,
} from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";

/**
 * Contexto de mercado y salud competitiva — las dos tiras de `overview`.
 *
 * Lo que se corrige respecto a la versión anterior:
 *
 * 1. **El delta ya no compara medio mes contra un mes entero.** `por_mes`
 *    agrupa por `substr(fecha_publicacion, 1, 7)`, así que su último bucket es
 *    el mes **en curso**. Comparándolo con el anterior, el día 2 de cada mes la
 *    pantalla de entrada abría con «−94 %» y con el badge de anomalía
 *    encendido, todos los meses, sin que hubiera pasado nada. Ahora la serie se
 *    recorta a meses cerrados y el rótulo dice cuáles compara («jul vs jun»),
 *    no un genérico «vs mes previo».
 * 2. **`yoy_delta` deja de colgar de «Órganos únicos».** Ese campo no es
 *    interanual ni habla de órganos: el backend lo calcula como
 *    `(licitaciones últimos 30 d − 30 d previos) / 30 d previos`. Iba pegado al
 *    recuento de órganos con el rótulo «YoY» — métrica, periodo y etiqueta
 *    equivocados en el mismo número de 11 px. Ahora acompaña a «Publicadas
 *    30 d», que es exactamente lo que mide.
 * 3. **La salud competitiva vuelve a la pantalla.** `hhi`, `pct_oferta_unica`,
 *    `pct_pyme`, `concentracion_top10`, `tasa_anulacion` y `lead_time_medio`
 *    llegaban en el mismo payload y no se pintaba ninguno, mientras la ficha de
 *    la página en `lib/navigation.ts` los prometía. Los cuatro que el backend
 *    calcula **sin filtros** (ver `overview_adjudicaciones_indicadores`) lo
 *    declaran en su pie: en una pantalla con chips activos, un número global
 *    sin marcar es un número que miente.
 *
 * La única cifra derivada en cliente es el badge de anomalía, y va etiquetado
 * como tal — la salida que el invariante 1 de `frontend-data-invariants.md`
 * permite («si un valor es estimado, etiquétalo»).
 */

interface MesAgregado {
  mes: string;
  n_licitaciones: number;
  importe: number;
}

/** Variación porcentual de `curr` sobre `prev`, o `undefined` si no se puede. */
function pctDelta(curr?: number, prev?: number): number | undefined {
  if (curr == null || prev == null || prev === 0) return undefined;
  return ((curr - prev) / prev) * 100;
}

/**
 * Serie mensual sin el mes en curso. Exportada porque es la corrección con
 * más consecuencias de este módulo y merece su propio test.
 */
export function mesesCerrados(porMes: MesAgregado[] | undefined, mesActual: string): MesAgregado[] {
  return (porMes ?? []).filter((mes) => mes.mes < mesActual);
}

export interface ComparativaMensual {
  count?: number;
  importe?: number;
  medio?: number;
  /** «jul vs jun» — vacío si no hay dos meses cerrados que comparar. */
  etiqueta: string;
  anomaliaCount: boolean;
  anomaliaImporte: boolean;
}

/** Compara los dos últimos meses **cerrados** de la serie del ámbito. */
export function compararMeses(
  porMes: MesAgregado[] | undefined,
  mesActual: string,
): ComparativaMensual {
  const cerrados = mesesCerrados(porMes, mesActual);
  if (cerrados.length < 2) {
    return { etiqueta: "", anomaliaCount: false, anomaliaImporte: false };
  }
  const ultimo = cerrados[cerrados.length - 1];
  const previo = cerrados[cerrados.length - 2];
  const mismoAnio = ultimo.mes.slice(0, 4) === previo.mes.slice(0, 4);
  const medioUltimo = ultimo.n_licitaciones ? ultimo.importe / ultimo.n_licitaciones : undefined;
  const medioPrevio = previo.n_licitaciones ? previo.importe / previo.n_licitaciones : undefined;
  const historia = cerrados.slice(0, -1);

  return {
    count: pctDelta(ultimo.n_licitaciones, previo.n_licitaciones),
    importe: pctDelta(ultimo.importe, previo.importe),
    medio: pctDelta(medioUltimo, medioPrevio),
    etiqueta: `${formatMonth(ultimo.mes, !mismoAnio)} vs ${formatMonth(previo.mes, !mismoAnio)}`,
    anomaliaCount: isAnomaly(
      ultimo.n_licitaciones,
      historia.map((mes) => mes.n_licitaciones),
    ),
    anomaliaImporte: isAnomaly(
      ultimo.importe,
      historia.map((mes) => mes.importe),
    ),
  };
}

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

const STRIP_6 = "lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]";
/** Pie de los indicadores que el backend calcula sobre la tabla entera. */
const GLOBAL = "corpus completo, no el ámbito";

export function ContextoStrip() {
  const overview = useFilteredQuery<AnalyticsOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60 * 1000 },
  );

  const data = overview.data;
  const loading = overview.isLoading;

  const comparativa = useMemo(() => {
    const mesActual = new Date().toISOString().slice(0, 7);
    return compararMeses(data?.por_mes, mesActual);
  }, [data?.por_mes]);

  // Nº de meses cerrados que sirven de historia al badge de anomalía (la serie
  // menos el mes que se está juzgando). `isAnomaly` ya se abstiene con menos de
  // tres, así que aquí sólo hace falta para redactar su tooltip.
  const historial = useMemo(() => {
    const mesActual = new Date().toISOString().slice(0, 7);
    return Math.max(0, mesesCerrados(data?.por_mes, mesActual).length - 1);
  }, [data?.por_mes]);

  const pieDelta = comparativa.etiqueta || "sin dos meses cerrados que comparar";

  if (overview.error) {
    return (
      <section aria-labelledby="resumen-contexto" className="mb-5.5">
        <h2 id="resumen-contexto" className="mb-2.5 text-xs font-semibold">
          Contexto de mercado
        </h2>
        <PanelError
          title="No se pudo cargar el contexto"
          detail={(overview.error as Error).message}
          onRetry={() => void overview.refetch()}
        />
      </section>
    );
  }

  return (
    <>
      <section aria-labelledby="resumen-contexto" className="mb-5.5">
        <div className="mb-2.5 flex items-baseline gap-2.5">
          <h2 id="resumen-contexto" className="text-xs font-semibold">
            Contexto de mercado
          </h2>
          <span className="text-muted-foreground text-[10.5px]">
            del ámbito activo · deltas entre meses cerrados
          </span>
        </div>
        <StatStrip columns={6} className={STRIP_6}>
          <StatCell
            label="Total licitaciones"
            loading={loading}
            value={formatNumber(data?.total_licitaciones)}
            trend={comparativa.count}
            hint={pieDelta}
            badge={
              comparativa.anomaliaCount ? <BadgeAnomalia meses={historial} /> : undefined
            }
          />
          <StatCell
            label="Importe total"
            loading={loading}
            value={formatCompactCurrency(data?.importe_total)}
            trend={comparativa.importe}
            hint={pieDelta}
            badge={
              comparativa.anomaliaImporte ? <BadgeAnomalia meses={historial} /> : undefined
            }
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

      <section aria-labelledby="resumen-salud" className="mb-5.5">
        <div className="mb-2.5 flex items-baseline gap-2.5">
          <h2 id="resumen-salud" className="text-xs font-semibold">
            Salud competitiva
          </h2>
          <span className="text-muted-foreground text-[10.5px]">
            cuatro de los seis se calculan sobre el corpus entero · lo dice su pie
          </span>
        </div>
        <StatStrip columns={6} className={STRIP_6}>
          <StatCell
            label="HHI adjudicatarios"
            loading={loading}
            value={data ? formatNumber(Math.round(data.hhi)) : EMPTY}
            hint={`0–10.000 · ${GLOBAL}`}
          />
          <StatCell
            label="Oferta única"
            loading={loading}
            value={formatPercent(data?.pct_oferta_unica)}
            hint={`adjudicaciones con 1 oferta · ${GLOBAL}`}
          />
          <StatCell
            label="PYME adjudicataria"
            loading={loading}
            value={formatPercent(data?.pct_pyme)}
            hint={GLOBAL}
          />
          <StatCell
            label="Lead time medio"
            loading={loading}
            value={data?.lead_time_medio != null ? `${formatNumber(data.lead_time_medio)} d` : EMPTY}
            hint={`publicación → adjudicación · ${GLOBAL}`}
          />
          <StatCell
            label="Top-10 órganos"
            loading={loading}
            value={formatPercent(data?.concentracion_top10)}
            hint="del importe del ámbito"
          />
          <StatCell
            label="Anulación 12 m"
            loading={loading}
            value={formatPercent(data?.tasa_anulacion)}
            hint="expedientes anulados en el ámbito"
          />
        </StatStrip>
      </section>
    </>
  );
}
