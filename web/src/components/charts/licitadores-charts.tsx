"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Line,
  ComposedChart,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface LicitadorBarEntry {
  nombre: string;
  count: number;
  importe: number;
}

interface GeoCcaaEntry {
  ccaa: string;
  count: number;
}

interface EstacionalidadEntry {
  mes: string;
  count: number;
  importe: number;
}

interface EvolutionEntry {
  nombre: string;
  importe: number;
  count: number;
  importe_medio: number;
}

/* ── Exported chart components ─────────────────────────────────── */

export function LicitadoresRankingBarChart({ data }: { data: LicitadorBarEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(400, data.length * 32)}>
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
            tickFormatter={(v: string) => truncate(v, 30)}
          />
          <Tooltip formatter={(v) => formatNumber(v as number)} />
          <Bar dataKey="count" fill="hsl(160, 60%, 45%)" radius={[0, 4, 4, 0]} name="Adjudicaciones" />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function LicitadoresGeoCcaaChart({ data }: { data: GeoCcaaEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(300, data.length * 30)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ left: 140 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 12 }} />
          <YAxis
            dataKey="ccaa"
            type="category"
            tick={{ fontSize: 11 }}
            width={130}
          />
          <Tooltip formatter={(v) => [formatNumber(v as number), "Adjudicaciones"]} />
          <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Adjudicaciones" />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function LicitadoresEstacionalidadChart({ data }: { data: EstacionalidadEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={350}>
        <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="mes" tick={{ fontSize: 12 }} />
          <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatCurrency(v)} />
          <Tooltip
            formatter={(v, name) =>
              name === "Importe" ? formatCurrency(Number(v ?? 0)) : formatNumber(Number(v ?? 0))
            }
          />
          <Legend />
          <Bar yAxisId="left" dataKey="count" fill={CHART_SERIES[0]} radius={[4, 4, 0, 0]} name="Adjudicaciones" />
          <Line yAxisId="right" type="monotone" dataKey="importe" stroke={CHART_SERIES[1]} strokeWidth={2} dot={{ r: 3 }} name="Importe" />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function LicitadoresTop10ImporteChart({ data }: { data: EvolutionEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(350, data.length * 35)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ left: 160, right: 20 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatCurrency(v)} />
          <YAxis dataKey="nombre" type="category" tick={{ fontSize: 11 }} width={150} />
          <Tooltip formatter={(v) => [formatCurrency(v as number), "Importe"]} />
          <Bar dataKey="importe" fill={CHART_SERIES[0]} name="Importe Total" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
