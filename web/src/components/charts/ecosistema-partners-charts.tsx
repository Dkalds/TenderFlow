"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface WinnerEntry {
  nombre: string;
  count: number;
  importe: number;
}

/* ── Exported chart components ─────────────────────────────────── */

export function GanadoresCountBarChart({ data }: { data: WinnerEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(350, data.length * 30)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ left: 180 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 12 }} />
          <YAxis
            dataKey="nombre"
            type="category"
            tick={{ fontSize: 11 }}
            width={170}
            tickFormatter={(v: string) => truncate(v, 28)}
          />
          <Tooltip formatter={(v) => [formatNumber(v as number), "Adjudicaciones"]} />
          <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Adjudicaciones" />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function GanadoresImporteBarChart({ data }: { data: WinnerEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(350, data.length * 30)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ left: 180 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
          <YAxis
            dataKey="nombre"
            type="category"
            tick={{ fontSize: 11 }}
            width={170}
            tickFormatter={(v: string) => truncate(v, 28)}
          />
          <Tooltip formatter={(v) => [formatCurrency(v as number), "Importe"]} />
          <Bar dataKey="importe" fill={CHART_SERIES[1]} radius={[0, 4, 4, 0]} name="Importe" />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
