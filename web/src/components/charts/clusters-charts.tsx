"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { getSeriesColor } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface ClusterBarEntry {
  label: string;
  n: number;
  cluster_id: number;
}

export interface BoxDatum {
  label: string;
  _pad: number;
  _low: number;
  _boxLow: number;
  _boxHigh: number;
  _high: number;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  color: string;
}

function BoxTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: BoxDatum }[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border bg-background p-2 text-xs shadow-md">
      <p className="mb-1 font-medium">{d.label}</p>
      <p>max: {formatCurrency(d.max)}</p>
      <p>Q3: {formatCurrency(d.q3)}</p>
      <p className="font-medium">mediana: {formatCurrency(d.median)}</p>
      <p>Q1: {formatCurrency(d.q1)}</p>
      <p>min: {formatCurrency(d.min)}</p>
    </div>
  );
}

/* ── Exported chart components ─────────────────────────────────── */

export function ClustersBarChart({ data }: { data: ClusterBarEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(320, data.length * 32)}>
        <BarChart data={data} layout="vertical" margin={{ left: 150 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis dataKey="label" type="category" width={150} tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v) => [formatNumber(v as number), "Licitaciones"]} />
          <Bar dataKey="n" radius={[0, 4, 4, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={getSeriesColor(i)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function ClustersBoxChart({ data }: { data: BoxDatum[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(320, data.length * 32)}>
        <BarChart data={data} layout="vertical" margin={{ left: 130 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            tick={{ fontSize: 10 }}
            tickFormatter={(v: number) => formatCurrency(v)}
          />
          <YAxis dataKey="label" type="category" width={120} tick={{ fontSize: 10 }} />
          <Tooltip content={<BoxTooltip />} />
          <Bar dataKey="_pad" stackId="b" fill="transparent" />
          <Bar dataKey="_low" stackId="b" fill="hsl(var(--muted-foreground))" fillOpacity={0.2} />
          <Bar dataKey="_boxLow" stackId="b">
            {data.map((b, i) => (
              <Cell key={i} fill={b.color} fillOpacity={0.95} />
            ))}
          </Bar>
          <Bar dataKey="_boxHigh" stackId="b">
            {data.map((b, i) => (
              <Cell key={i} fill={b.color} fillOpacity={0.55} />
            ))}
          </Bar>
          <Bar dataKey="_high" stackId="b" fill="hsl(var(--muted-foreground))" fillOpacity={0.2} />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
