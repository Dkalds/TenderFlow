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
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber } from "@/lib/utils";

import { modeloLabel, type ForecastResponse, type ForecastRow } from "../_hooks/forecast-series";
import type { ForecastMetric } from "../_hooks/use-tendencias-view";

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
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1">
          <CardTitle className="text-base">Previsión (6 meses)</CardTitle>
          {/*
            La banda sombreada NO es un intervalo de confianza: es ±Nσ de toda
            la serie histórica, el MISMO valor para los seis horizontes (un IC
            real se ensancha con el horizonte). Los sigmas y el modelo los
            publica el backend — rotularlos aquí evita que el gráfico se lea
            como una incertidumbre estimada que nadie estimó.
          */}
          <CardDescription>
            {forecast?.banda_sigmas != null
              ? `Banda aproximada ≈${formatNumber(forecast.banda_sigmas)}σ de la serie histórica; no es un intervalo de confianza (no crece con el horizonte).`
              : "Banda aproximada sobre la desviación de la serie histórica; no es un intervalo de confianza (no crece con el horizonte)."}
            {modeloLabel(forecast?.modelo)
              ? ` Modelo: ${modeloLabel(forecast?.modelo)}.`
              : ""}
          </CardDescription>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant={metric === "count" ? "default" : "outline"}
            size="sm"
            onClick={() => onMetricChange("count")}
          >
            Cantidad
          </Button>
          <Button
            variant={metric === "sum" ? "default" : "outline"}
            size="sm"
            onClick={() => onMetricChange("sum")}
          >
            Importe
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[350px] w-full" />
        ) : data.length > 0 ? (
          <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <AreaChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="mes" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => metric === "sum" ? formatCurrency(v) : formatNumber(v)} />
              <Tooltip formatter={(value) => [metric === "sum" ? formatCurrency(value as number) : formatNumber(value as number), ""]} />
              {/* Confidence band */}
              <Area type="monotone" dataKey="upper" stroke="none" fill="hsl(221, 83%, 53%)" fillOpacity={0.1} name="Upper" />
              {/* "Goma" de la banda: el token de fondo de la card (no blanco) para que sea theme-safe en dark mode. */}
              <Area type="monotone" dataKey="lower" stroke="none" fill="hsl(var(--card))" fillOpacity={1} name="Lower" />
              {/* Historical line */}
              <Line type="monotone" dataKey="historico" stroke="hsl(221, 83%, 53%)" strokeWidth={2} dot={{ r: 2 }} name="Histórico" />
              {/* Forecast line */}
              <Line type="monotone" dataKey="forecast_val" stroke="hsl(221, 83%, 53%)" strokeWidth={2} strokeDasharray="6 3" dot={{ r: 2 }} name="Previsión" />
            </AreaChart>
          </ResponsiveContainer>
            </ChartErrorBoundary>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}
