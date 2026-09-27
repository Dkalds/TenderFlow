"use client";

/**
 * Previsión de volumen a seis meses, con el conmutador cantidad/importe.
 *
 * La banda sombreada se rotula con el modelo y los sigmas que publica el
 * backend porque NO es un intervalo de confianza; el texto lo explica en la
 * propia tarjeta.
 */

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Panel, PanelEmpty, PanelLoading, PanelTitle, Segmented } from "@/components/console/panel";
import { getSeriesColor } from "@/lib/chart-colors";
import { formatCurrency, formatNumber } from "@/lib/utils";

import { modeloLabel, type ForecastResponse, type ForecastRow } from "../_hooks/forecast-series";
import type { ForecastMetric } from "../_hooks/use-tendencias-view";

const METRICAS: { value: ForecastMetric; label: string }[] = [
  { value: "count", label: "Licitaciones" },
  { value: "sum", label: "Importe" },
];

export function TendenciasForecast({
  forecast,
  data,
  metric,
  onMetricChange,
  isLoading,
}: {
  /** Respuesta cruda: de ella salen el modelo y los sigmas que se rotulan. */
  forecast: ForecastResponse | undefined;
  data: ForecastRow[];
  metric: ForecastMetric;
  onMetricChange: (metric: ForecastMetric) => void;
  isLoading: boolean;
}) {
  const color = getSeriesColor(1);
  const modelo = modeloLabel(forecast?.modelo);
  return (
    <Panel>
      <PanelTitle
        title="Previsión a 6 meses"
        className="mb-1"
        actions={
          <Segmented value={metric} onChange={onMetricChange} options={METRICAS} aria-label="Métrica de la previsión" />
        }
      />
      {/*
        La banda sombreada NO es un intervalo de confianza: es ±Nσ de toda
        la serie histórica, el MISMO valor para los seis horizontes (un IC
        real se ensancha con el horizonte). Los sigmas y el modelo los
        publica el backend — rotularlos aquí evita que el gráfico se lea
        como una incertidumbre estimada que nadie estimó.
      */}
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Estimación.{" "}
        {forecast?.banda_sigmas != null
          ? `La banda sombreada es aproximada (±${formatNumber(forecast.banda_sigmas)}σ de la serie histórica) y no se ensancha con el horizonte: no es un intervalo de confianza.`
          : "La banda sombreada es aproximada y no se ensancha con el horizonte: no es un intervalo de confianza."}
        {modelo ? ` Modelo: ${modelo}.` : ""}
      </p>
      {isLoading ? (
        <PanelLoading height={350} />
      ) : data.length > 0 ? (
        <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <AreaChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="mes" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => metric === "sum" ? formatCurrency(v) : formatNumber(v)} />
              <Tooltip formatter={(value) => [metric === "sum" ? formatCurrency(value as number) : formatNumber(value as number), ""]} />
              {/* Banda aproximada */}
              <Area type="monotone" dataKey="upper" stroke="none" fill={color} fillOpacity={0.1} name="Banda (máximo)" />
              {/* "Goma" de la banda: el token de fondo de la card (no blanco) para que sea theme-safe en dark mode. */}
              <Area type="monotone" dataKey="lower" stroke="none" fill="hsl(var(--card))" fillOpacity={1} name="Banda (mínimo)" />
              <Line type="monotone" dataKey="historico" stroke={color} strokeWidth={2} dot={{ r: 2 }} name="Histórico" />
              <Line type="monotone" dataKey="forecast_val" stroke={color} strokeWidth={2} strokeDasharray="6 3" dot={{ r: 2 }} name="Previsión" />
            </AreaChart>
          </ResponsiveContainer>
        </ChartErrorBoundary>
      ) : (
        <PanelEmpty
          title="Sin previsión"
          hint="La serie del ámbito actual es demasiado corta para prever. Amplía las fechas."
          height={350}
        />
      )}
    </Panel>
  );
}
