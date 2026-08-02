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
    <div className="tf-tnum min-w-[10rem] rounded-md border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <p className="mb-1 text-xs font-semibold text-foreground">{d.label}</p>
      <dl className="space-y-0.5">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">max</dt>
          <dd className="font-medium">{formatCurrency(d.max)}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">Q3</dt>
          <dd className="font-medium">{formatCurrency(d.q3)}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">mediana</dt>
          <dd className="font-semibold text-primary">{formatCurrency(d.median)}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">Q1</dt>
          <dd className="font-medium">{formatCurrency(d.q1)}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">min</dt>
          <dd className="font-medium">{formatCurrency(d.min)}</dd>
        </div>
      </dl>
    </div>
  );
}

/* ── Exported chart components ─────────────────────────────────── */

export function ClustersBarChart({ data }: { data: ClusterBarEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(320, data.length * 32)}>
        <BarChart accessibilityLayer data={data} layout="vertical" margin={{ left: 150 }}>
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
        <BarChart accessibilityLayer data={data} layout="vertical" margin={{ left: 130 }}>
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
