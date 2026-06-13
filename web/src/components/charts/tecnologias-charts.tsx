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
  AreaChart,
  Area,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { getSeriesColor } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

export interface TecnologiaItem {
  tecnologia: string;
  count: number;
  importe: number;
  importe_medio: number;
  pct: number;
  pct_adjudicado: number;
}

interface VolumeBarEntry extends TecnologiaItem {
  _color: string;
}

interface DonutEntry {
  tecnologia: string;
  count: number;
  importe: number;
}

/* ── Exported chart components ─────────────────────────────────── */

export function TecnologiasEvolutionChart({
  data,
  techs,
  trendMetric,
}: {
  data: Record<string, number | string>[];
  techs: string[];
  trendMetric: "count" | "importe";
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={340}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="mes" tick={{ fontSize: 11 }} />
          <YAxis
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) =>
              trendMetric === "importe" ? formatCurrency(v) : formatNumber(v)
            }
          />
          <Tooltip
            formatter={(v, name) => [
              trendMetric === "importe"
                ? formatCurrency(v as number)
                : formatNumber(v as number),
              name as string,
            ]}
          />
          <Legend />
          {techs.map((tech, idx) => (
            <Area
              key={tech}
              type="monotone"
              dataKey={tech}
              name={tech}
              stackId="1"
              stroke={getSeriesColor(idx)}
              fill={getSeriesColor(idx)}
              fillOpacity={0.5}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function TecnologiasVolumeBarChart({
  data,
}: {
  data: VolumeBarEntry[];
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(300, data.length * 28)}>
        <BarChart data={data} layout="vertical" margin={{ left: 110 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis dataKey="tecnologia" type="category" width={100} tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(v, _n, p) => [
              `${formatNumber(v as number)} lic · ${formatCurrency(
                (p?.payload as TecnologiaItem)?.importe ?? 0,
              )}`,
              "Volumen",
            ]}
          />
          <Bar dataKey="count" radius={[0, 4, 4, 0]}>
            {data.map((entry, idx) => (
              <Cell key={idx} fill={entry._color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function TecnologiasImporteBarChart({
  data,
}: {
  data: VolumeBarEntry[];
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(300, data.length * 28)}>
        <BarChart data={data} layout="vertical" margin={{ left: 110 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => formatCurrency(v)}
          />
          <YAxis dataKey="tecnologia" type="category" width={100} tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(v, _n, p) => [
              `${formatCurrency(v as number)} · ${formatNumber(
                (p?.payload as TecnologiaItem)?.count ?? 0,
              )} lic`,
              "Importe",
            ]}
          />
          <Bar dataKey="importe" radius={[0, 4, 4, 0]}>
            {data.map((entry, idx) => (
              <Cell key={idx} fill={entry._color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function TecnologiasDonutChart({ data }: { data: DonutEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="tecnologia"
            cx="50%"
            cy="50%"
            innerRadius={70}
            outerRadius={140}
            label={({ name, percent }: { name?: string; percent?: number }) =>
              `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
            }
            labelLine={{ strokeWidth: 1 }}
          >
            {data.map((_, idx) => (
              <Cell key={idx} fill={getSeriesColor(idx)} />
            ))}
          </Pie>
          <Tooltip formatter={(value) => formatNumber(value as number)} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function TecnologiasGeoBarChart({
  data,
  techs,
}: {
  data: Record<string, number | string>[];
  techs: string[];
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(360, data.length * 34)}>
        <BarChart data={data} layout="vertical" margin={{ left: 90 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis dataKey="ccaa" type="category" width={84} tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v, name) => [formatNumber(v as number), name as string]} />
          <Legend />
          {techs.map((tech, idx) => (
            <Bar key={tech} dataKey={tech} name={tech} fill={getSeriesColor(idx)} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
