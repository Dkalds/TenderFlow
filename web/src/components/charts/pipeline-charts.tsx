"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  Cell,
  ReferenceLine,
  Line,
  Area,
  ComposedChart,
  Legend,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { numberFormatter, smartFormatter } from "@/lib/chart-formatters";
import { URGENCY_COLORS } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface HorizonteCount {
  horizonte: string;
  count: number;
  importe: number;
}

interface TrimestreCount {
  trimestre: string;
  count: number;
  importe: number;
}

export interface UrgenciaValorPoint {
  id_externo: string;
  titulo?: string | null;
  dias_restantes: number;
  importe: number;
  es_urgente: boolean;
}

const HORIZON_COLORS: Record<string, string> = {
  "0-7d": URGENCY_COLORS.critical,
  "7-30d": URGENCY_COLORS.high,
  "30-90d": URGENCY_COLORS.medium,
  "90+d": URGENCY_COLORS.low,
};

function horizonColor(label: string) {
  for (const [key, color] of Object.entries(HORIZON_COLORS)) {
    if (label.includes(key) || label.toLowerCase().includes(key)) return color;
  }
  if (label.includes("7")) return URGENCY_COLORS.critical;
  if (label.includes("30")) return URGENCY_COLORS.high;
  if (label.includes("90")) return URGENCY_COLORS.medium;
  return URGENCY_COLORS.low;
}

/* ── Exported chart components ─────────────────────────────────── */

export function PipelineHorizonChart({ data }: { data: HorizonteCount[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis type="category" dataKey="horizonte" width={80} tick={{ fontSize: 12 }} />
          <Tooltip formatter={numberFormatter} />
          <Bar dataKey="count" name="Licitaciones" radius={[0, 4, 4, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={horizonColor(entry.horizonte)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function PipelineQuarterlyChart({ data }: { data: TrimestreCount[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="trimestre" tick={{ fontSize: 11 }} />
          <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => formatCurrency(v)}
          />
          <Tooltip formatter={smartFormatter} />
          <Legend />
          <Bar
            yAxisId="left"
            dataKey="count"
            name="Licitaciones"
            fill="hsl(var(--primary))"
            radius={[4, 4, 0, 0]}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="importe"
            name="Importe"
            stroke="hsl(var(--chart-2))"
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export interface ForecastVolPoint {
  mes: string;
  valor: number;
  tipo: string;
  lower: number | null;
  upper: number | null;
}

/**
 * Forecast de volumen de licitaciones para los próximos meses con banda de
 * confianza (~1.5σ). El backend (`/api/v1/analytics/forecast/volume`) entrega
 * la serie histórica + previsión; aquí solo se renderiza. La banda se dibuja
 * con dos áreas (upper relleno + lower "goma" con el fondo de la card, theme-safe).
 */
export function PipelineForecastChart({
  data,
  metric = "count",
}: {
  data: ForecastVolPoint[];
  metric?: "count" | "sum";
}) {
  const rows = data.map((p) => {
    const isForecast = p.tipo === "forecast";
    return {
      mes: p.mes,
      historico: isForecast ? undefined : p.valor,
      forecast_val: isForecast ? p.valor : undefined,
      lower: isForecast ? (p.lower ?? undefined) : undefined,
      upper: isForecast ? (p.upper ?? undefined) : undefined,
    };
  });
  // Conecta el tramo histórico con la previsión repitiendo el último punto real.
  let lastHistIdx = -1;
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i].tipo !== "forecast") {
      lastHistIdx = i;
      break;
    }
  }
  if (lastHistIdx >= 0 && lastHistIdx < rows.length) {
    rows[lastHistIdx].forecast_val = rows[lastHistIdx].historico;
  }

  const axisFmt = (v: number) => (metric === "sum" ? formatCurrency(v) : formatNumber(v));
  const tipFmt = (v: RechartTipValue) =>
    metric === "sum" ? formatCurrency(Number(v)) : formatNumber(Number(v));

  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={rows} margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="mes" tick={{ fontSize: 11 }} angle={-35} textAnchor="end" height={56} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={axisFmt} width={70} />
          <Tooltip formatter={(value, name) => [tipFmt(value as RechartTipValue), name]} />
          <Legend />
          {/* Banda de confianza */}
          <Area
            type="monotone"
            dataKey="upper"
            stroke="none"
            fill="hsl(var(--primary))"
            fillOpacity={0.12}
            name="Banda"
            legendType="none"
          />
          <Area
            type="monotone"
            dataKey="lower"
            stroke="none"
            fill="hsl(var(--card))"
            fillOpacity={1}
            name="lower"
            legendType="none"
          />
          {/* Línea histórica */}
          <Line
            type="monotone"
            dataKey="historico"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            dot={{ r: 2 }}
            name="Histórico"
            connectNulls
          />
          {/* Línea de previsión */}
          <Line
            type="monotone"
            dataKey="forecast_val"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            strokeDasharray="6 3"
            dot={{ r: 2 }}
            name="Previsión"
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

type RechartTipValue = string | number | ReadonlyArray<string | number> | undefined;

export function PipelineUrgencyScatter({
  data,
  onPointClick,
}: {
  data: UrgenciaValorPoint[];
  onPointClick?: (id: string) => void;
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" dataKey="dias_restantes" name="Dias restantes" tick={{ fontSize: 11 }} />
          <YAxis
            type="number"
            dataKey="importe"
            name="Importe"
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => formatCurrency(v)}
          />
          <Tooltip formatter={smartFormatter} />
          <ReferenceLine
            x={7}
            stroke={URGENCY_COLORS.critical}
            strokeDasharray="5 5"
            label={{ value: "7d", fill: URGENCY_COLORS.critical, fontSize: 11 }}
          />
          <Scatter
            data={data}
            name="Oportunidades"
            onClick={(node) => {
              const n = node as unknown as {
                id_externo?: string;
                payload?: { id_externo?: string };
              };
              const id = n?.id_externo ?? n?.payload?.id_externo;
              if (onPointClick && id) onPointClick(id);
            }}
          >
            {data.map((point, i) => (
              <Cell key={i} fill={point.es_urgente ? URGENCY_COLORS.critical : "hsl(var(--chart-10))"} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
