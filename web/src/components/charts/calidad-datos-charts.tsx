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
  Legend,
  Line,
  LineChart,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CHART_SERIES, URGENCY_COLORS } from "@/lib/chart-colors";

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
        <BarChart accessibilityLayer
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

/* ── Tendencia de completitud (RFC calidad #3) ─────────────────── */

interface CompletitudMesEntry {
  mes: string;
  pct_cpv: number;
  pct_importe: number;
  pct_organo: number;
  pct_fecha_limite: number;
}

const TENDENCIA_SERIES: { key: keyof Omit<CompletitudMesEntry, "mes">; name: string }[] = [
  { key: "pct_cpv", name: "CPV" },
  { key: "pct_importe", name: "Importe" },
  { key: "pct_organo", name: "Órgano" },
  { key: "pct_fecha_limite", name: "Fecha límite" },
];

export function CalidadTendenciaChart({ data }: { data: CompletitudMesEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart accessibilityLayer data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="mes" tick={{ fontSize: 12 }} />
          <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} />
          <Tooltip formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name]} />
          <Legend />
          {TENDENCIA_SERIES.map((s, i) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.name}
              stroke={CHART_SERIES[i % CHART_SERIES.length]}
              strokeWidth={2}
              dot={{ r: 2 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
