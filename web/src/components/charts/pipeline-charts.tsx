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
  ComposedChart,
  Legend,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency } from "@/lib/utils";
import { numberFormatter, smartFormatter } from "@/lib/chart-formatters";

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
  titulo?: string;
  dias_restantes: number;
  importe: number;
  es_urgente: boolean;
}

const HORIZON_COLORS: Record<string, string> = {
  "0-7d": "#ef4444",
  "7-30d": "#f97316",
  "30-90d": "#eab308",
  "90+d": "#22c55e",
};

function horizonColor(label: string) {
  for (const [key, color] of Object.entries(HORIZON_COLORS)) {
    if (label.includes(key) || label.toLowerCase().includes(key)) return color;
  }
  if (label.includes("7")) return "#ef4444";
  if (label.includes("30")) return "#f97316";
  if (label.includes("90")) return "#eab308";
  return "#22c55e";
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
            stroke="#f97316"
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function PipelineUrgencyScatter({ data }: { data: UrgenciaValorPoint[] }) {
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
            stroke="#ef4444"
            strokeDasharray="5 5"
            label={{ value: "7d", fill: "#ef4444", fontSize: 11 }}
          />
          <Scatter data={data} name="Oportunidades">
            {data.map((point, i) => (
              <Cell key={i} fill={point.es_urgente ? "#ef4444" : "#3b82f6"} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
