"use client";

/**
 * Los cuatro gráficos de la serie mensual de Tendencias: volumen por mes,
 * importe acumulado, el waterfall de variación y el histograma de importes.
 *
 * El waterfall se carga bajo demanda (`ssr: false`): mide el ancho del
 * contenedor para repartir las barras, así que en servidor no tiene nada que
 * medir.
 */

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { getSeriesColor } from "@/lib/chart-colors";
import { useScopedHref } from "@/lib/filters";
import { formatCurrency, formatNumber } from "@/lib/utils";
import type { TrendPoint } from "@/lib/api-types";

import {
  mesHref,
  type CumulativePoint,
  type HistogramBin,
  type WaterfallPoint,
} from "../_hooks/use-tendencias-view";

const WaterfallChart = dynamic(() => import("@/components/charts/waterfall-chart").then(m => ({ default: m.WaterfallChart })), { ssr: false, loading: () => <PanelLoading height={320} /> });

const VACIO_SERIE = "Ninguna licitación publicada en el ámbito actual. Amplía las fechas o quita filtros.";

export function TendenciasVolumen({
  series,
  isLoading,
}: {
  series: TrendPoint[];
  isLoading: boolean;
}) {
  // Drill-down (RFC ux-tendencias #3): la barra de un mes abre el listado de
  // lo publicado ese mes, con el resto del ámbito activo. El camino de
  // teclado equivalente son las cabeceras de mes del heatmap Mes×Estado.
  const router = useRouter();
  const scopedHref = useScopedHref();
  const abrirMes = (dato: unknown) => {
    const periodo = (dato as { payload?: TrendPoint } | undefined)?.payload?.period;
    if (periodo && /^\d{4}-\d{2}$/.test(periodo)) router.push(scopedHref(mesHref(periodo)));
  };
  return (
    <Panel>
      <PanelTitle title="Licitaciones por mes" hint="Pulsa una barra para ver las licitaciones de ese mes" />
      {isLoading ? (
        <PanelLoading height={350} />
      ) : series.length > 0 ? (
        <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart accessibilityLayer data={series}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => [formatNumber(value as number), "Licitaciones"]} />
              <Bar
                dataKey="count"
                fill={getSeriesColor(1)}
                radius={[4, 4, 0, 0]}
                name="Licitaciones"
                className="cursor-pointer"
                onClick={abrirMes}
              />
            </BarChart>
          </ResponsiveContainer>
        </ChartErrorBoundary>
      ) : (
        <PanelEmpty title="Sin licitaciones" hint={VACIO_SERIE} height={350} />
      )}
    </Panel>
  );
}

export function TendenciasAcumulado({
  data,
  isLoading,
}: {
  data: CumulativePoint[];
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title="Importe acumulado" />
      {isLoading ? (
        <PanelLoading height={350} />
      ) : data.length > 0 ? (
        <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <AreaChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
              <Tooltip formatter={(value) => [formatCurrency(value as number), "Acumulado"]} />
              <Area
                type="monotone"
                dataKey="importe_acumulado"
                stroke={getSeriesColor(5)}
                fill={getSeriesColor(5)}
                fillOpacity={0.15}
                name="Importe acumulado"
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartErrorBoundary>
      ) : (
        <PanelEmpty title="Sin importes" hint={VACIO_SERIE} height={350} />
      )}
    </Panel>
  );
}

/** Variación del NÚMERO de licitaciones de un mes al siguiente (no del importe). */
export function TendenciasWaterfall({ data }: { data: WaterfallPoint[] }) {
  return (
    <Panel>
      <PanelTitle title="Variación mensual del número de licitaciones" />
      <WaterfallChart data={data} height={320} />
    </Panel>
  );
}

export function TendenciasHistograma({
  bins,
  /** Rango dinámico > 100×: sin escala log las colas se aplastan contra el eje. */
  useLogScale,
}: {
  bins: HistogramBin[];
  useLogScale: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        title="Licitaciones por tramo de importe"
        hint={useLogScale ? "Escala logarítmica: los tramos pequeños no se aplastan" : undefined}
      />
      <ChartErrorBoundary>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart accessibilityLayer data={bins} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <YAxis dataKey="bin_label" type="category" tick={{ fontSize: 12 }} width={120} />
            <XAxis
              type="number"
              tick={{ fontSize: 12 }}
              scale={useLogScale ? "log" : "auto"}
              domain={useLogScale ? [1, "auto"] : [0, "auto"]}
              tickFormatter={(v: number) => formatNumber(v)}
            />
            <Tooltip formatter={(value) => [formatNumber(value as number), "Licitaciones"]} />
            <Bar dataKey="count" fill={getSeriesColor(4)} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </ChartErrorBoundary>
    </Panel>
  );
}
