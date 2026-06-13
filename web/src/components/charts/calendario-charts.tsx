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
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber } from "@/lib/utils";

/* ── Types ─────────────────────────────────────────────────────── */

interface MonthlyEntry {
  mes: string;
  publicaciones: number;
  importe: number;
}

interface DowEntry {
  dia: string;
  promedio: number;
}

/* ── Exported chart components ─────────────────────────────────── */

export function CalendarioMonthlyChart({ data }: { data: MonthlyEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="mes" tick={{ fontSize: 12 }} />
          <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 12 }}
            tickFormatter={(v: number) => formatCurrency(v)}
          />
          <Tooltip
            formatter={(value, name) =>
              name === "Importe" ? formatCurrency(Number(value ?? 0)) : formatNumber(Number(value ?? 0))
            }
          />
          <Legend />
          <Bar yAxisId="left" dataKey="publicaciones" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]} name="Publicaciones" />
          <Bar yAxisId="right" dataKey="importe" fill="hsl(160, 60%, 45%)" radius={[4, 4, 0, 0]} name="Importe" />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function CalendarioDowChart({ data }: { data: DowEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="dia" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          <Bar dataKey="promedio" fill="hsl(280, 65%, 60%)" radius={[4, 4, 0, 0]} name="Promedio diario" />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
