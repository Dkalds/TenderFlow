"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface GeoBarEntry {
  ccaa: string;
  count: number;
  importe: number;
  pct: number;
}

interface GeoPieEntry {
  ccaa: string;
  importe: number;
}

/* ── Exported chart components ─────────────────────────────────── */

export function GeografiaBarChart({ data }: { data: GeoBarEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer
        width="100%"
        height={Math.max(300, data.length * 30)}
      >
        <BarChart
          data={data}
          layout="vertical"
          margin={{ left: 120 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            className="stroke-border"
          />
          <XAxis type="number" tick={{ fontSize: 12 }} />
          <YAxis
            dataKey="ccaa"
            type="category"
            width={120}
            tick={{ fontSize: 12 }}
          />
          <Tooltip
            formatter={(value) => [
              formatNumber(value as number),
              "Licitaciones",
            ]}
          />
          <Bar
            dataKey="count"
            fill={CHART_SERIES[0]}
            radius={[0, 4, 4, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function GeografiaPieChart({ data }: { data: GeoPieEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <PieChart>
          <Pie
            data={data}
            dataKey="importe"
            nameKey="ccaa"
            cx="50%"
            cy="50%"
            outerRadius={140}
            label={({
              name,
              percent,
            }: {
              name?: string;
              percent?: number;
            }) =>
              `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
            }
            labelLine={{ strokeWidth: 1 }}
          >
            {data.map((_, idx) => (
              <Cell
                key={idx}
                fill={getSeriesColor(idx)}
              />
            ))}
          </Pie>
          <Tooltip
            formatter={(value) => formatCurrency(value as number)}
          />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
