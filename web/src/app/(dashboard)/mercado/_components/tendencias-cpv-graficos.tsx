"use client";

/**
 * Los tres gráficos de Tendencias CPV: el multilínea de importe por periodo
 * (con el botón que abre la previsión), la previsión —de un CPV pintado o del
 * mercado entero, rotulada con el ámbito que declara la API— y el ranking Top
 * 15 por importe.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import { formatCurrency, formatNumber } from "@/lib/utils";

import type { ForecastRow } from "../_hooks/forecast-series";
import type {
  CpvChartRow,
  CpvSeries,
  TopCpv,
} from "../_hooks/use-tendencias-cpv-view";

const VACIO_CPV = "Ningún CPV con licitaciones en el ámbito actual. Amplía las fechas o quita filtros.";

export function TendenciasCpvSeries({
  allCpvs,
  effectiveCpvs,
  data,
  showForecast,
  onToggleForecast,
  isLoading,
}: {
  allCpvs: CpvSeries[];
  effectiveCpvs: Set<string>;
  data: CpvChartRow[];
  showForecast: boolean;
  onToggleForecast: () => void;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        title="Importe por periodo"
        hint={effectiveCpvs.size > 0 ? `${formatNumber(effectiveCpvs.size)} CPV` : undefined}
        actions={
          <Button
            variant={showForecast ? "secondary" : "outline"}
            size="sm"
            aria-pressed={showForecast}
            onClick={onToggleForecast}
          >
            Previsión
          </Button>
        }
      />
      {isLoading ? (
        <PanelLoading height={350} />
      ) : data.length > 0 ? (
        <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <LineChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
              <Tooltip formatter={(value) => [formatCurrency(value as number), ""]} />
              {allCpvs
                .filter((c) => effectiveCpvs.has(c.cpv))
                .map((c) => (
                  <Line
                    key={c.cpv}
                    type="monotone"
                    dataKey={c.cpv}
                    stroke={getSeriesColor(allCpvs.indexOf(c))}
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 4 }}
                    name={c.label || c.cpv}
                  />
                ))}
            </LineChart>
          </ResponsiveContainer>
        </ChartErrorBoundary>
      ) : (
        <PanelEmpty title="Sin serie" hint={VACIO_CPV} height={350} />
      )}
    </Panel>
  );
}

export function TendenciasCpvForecast({
  data,
  cpv,
  cpvRespuesta,
  opciones,
  onCpvChange,
  isLoading,
}: {
  data: ForecastRow[];
  /** CPV pedido; `null` = mercado entero. */
  cpv: string | null;
  /** CPV que declara la respuesta: es el que se rotula, no el que se creía pedir. */
  cpvRespuesta: string | null;
  opciones: CpvSeries[];
  onCpvChange: (cpv: string | null) => void;
  isLoading: boolean;
}) {
  const esGlobal = cpvRespuesta == null;
  const etiquetaCpv = opciones.find((o) => o.cpv === cpvRespuesta)?.label ?? cpvRespuesta;
  return (
    <Panel>
      <PanelTitle
        title="Previsión de licitaciones a 6 meses"
        className="mb-1"
        actions={
          <>
            <Badge variant={esGlobal ? "warning" : "outline"} size="sm">
              {esGlobal ? "Todo el mercado" : `CPV ${cpvRespuesta}`}
            </Badge>
            <label className="flex items-center gap-2 text-tf-meta">
              <span className="text-muted-foreground">Prever</span>
              <select
                className="h-8 rounded-md border border-border/60 bg-card px-2 text-tf-meta md:h-7"
                value={cpv ?? ""}
                onChange={(e) => onCpvChange(e.target.value === "" ? null : e.target.value)}
              >
                {opciones.map((o) => (
                  <option key={o.cpv} value={o.cpv}>
                    {o.cpv}
                    {o.label && o.label !== o.cpv ? ` — ${o.label}` : ""}
                  </option>
                ))}
                <option value="">Mercado entero</option>
              </select>
            </label>
          </>
        }
      />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        {esGlobal ? (
          <>
            Estimación del volumen de <strong className="font-semibold text-foreground">todo el mercado</strong>,
            no de un CPV concreto.
          </>
        ) : (
          <>
            Estimación de las licitaciones del CPV{" "}
            <strong className="font-semibold text-foreground">{etiquetaCpv}</strong>, sobre su propia serie
            mensual.
          </>
        )}
      </p>
      {isLoading ? (
        <PanelLoading height={300} />
      ) : data.length > 0 ? (
        <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="mes" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Area type="monotone" dataKey="upper" stroke="none" fill={CHART_SERIES[0]} fillOpacity={0.1} name="Banda (máximo)" />
              {/* Goma theme-safe: token de fondo de la card, no blanco (rompía en dark mode). */}
              <Area type="monotone" dataKey="lower" stroke="none" fill="hsl(var(--card))" fillOpacity={1} name="Banda (mínimo)" />
              <Line type="monotone" dataKey="historico" stroke={CHART_SERIES[0]} strokeWidth={2} dot={{ r: 2 }} name="Histórico" />
              <Line type="monotone" dataKey="forecast_val" stroke={CHART_SERIES[0]} strokeWidth={2} strokeDasharray="6 3" dot={{ r: 2 }} name="Previsión" />
            </AreaChart>
          </ResponsiveContainer>
        </ChartErrorBoundary>
      ) : (
        <PanelEmpty
          title="Sin previsión"
          hint="La serie de este CPV es demasiado corta para prever. Prueba con otro o con el mercado entero."
          height={300}
        />
      )}
    </Panel>
  );
}

export function TendenciasCpvTop({
  topCpvs,
  isLoading,
}: {
  topCpvs: TopCpv[];
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title="Los 15 CPV con más importe" />
      {isLoading ? (
        <PanelLoading height={400} />
      ) : topCpvs.length > 0 ? (
        <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={Math.max(300, topCpvs.length * 30)}>
            <BarChart accessibilityLayer data={topCpvs} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <YAxis dataKey="cpv" type="category" tick={{ fontSize: 12 }} width={140} />
              <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
              <Tooltip formatter={(value) => [formatCurrency(value as number), "Importe"]} />
              <Bar dataKey="importe_total" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Importe" />
            </BarChart>
          </ResponsiveContainer>
        </ChartErrorBoundary>
      ) : (
        <PanelEmpty title="Ningún CPV" hint={VACIO_CPV} height={400} />
      )}
    </Panel>
  );
}
