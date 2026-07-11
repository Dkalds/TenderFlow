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
import { URGENCY_COLORS } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface ColumnCompleteness {
  columna: string;
  pct: number;
}

function barColor(pct: number): string {
  if (pct >= 90) return URGENCY_COLORS.low;
  if (pct >= 70) return URGENCY_COLORS.medium;
  return URGENCY_COLORS.critical;
}

/* ── Exported chart components ─────────────────────────────────── */

export function CalidadCompletenessChart({ data }: { data: ColumnCompleteness[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(data.length * 40, 200)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 5, right: 30, left: 80, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} unit="%" />
          <YAxis
            type="category"
            dataKey="columna"
            width={75}
            tick={{ fontSize: 12 }}
          />
          <Tooltip
            formatter={(value) => [`${Number(value).toFixed(1)}%`, "Completitud"]}
          />
          <Bar dataKey="pct" radius={[0, 4, 4, 0]} barSize={20}>
            {data.map((entry, idx) => (
              <Cell key={idx} fill={barColor(entry.pct)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
