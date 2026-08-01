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
  Treemap,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { TreemapContent } from "@/components/charts/treemap-content";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface ModuloBarEntry {
  modulo: string;
  count: number;
  importe: number;
}

interface TipoPieEntry {
  tipo: string;
  count: number;
  importe: number;
}

interface TreemapEntry {
  name: string;
  size: number;
  [key: string]: string | number;
}

interface TipoEstadoRow {
  tipo: string;
  [estado: string]: number | string;
}

/* ── Exported chart components ─────────────────────────────────── */

export function ModulosBarChart({ data }: { data: ModuloBarEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer
        width="100%"
        height={Math.max(300, data.length * 30)}
      >
        <BarChart accessibilityLayer
          data={data}
          layout="vertical"
          margin={{ left: 80 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            className="stroke-border"
          />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis
            dataKey="modulo"
            type="category"
            width={80}
            tick={{ fontSize: 11 }}
          />
          <Tooltip
            formatter={(value) => [
              formatNumber(value as number),
              "Licitaciones",
            ]}
          />
          <Bar
            dataKey="count"
            fill={CHART_SERIES[1]}
            radius={[0, 4, 4, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function TiposPieChart({ data }: { data: TipoPieEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="tipo"
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
            formatter={(value) => formatNumber(value as number)}
          />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function ModulosTreemap({ data }: { data: TreemapEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={350}>
        <Treemap
          data={data}
          dataKey="size"
          nameKey="name"
          content={<TreemapContent minWidth={35} minHeight={22} fontSize={10} valueFontSize={9} borderRadius={3} formatValue={(v) => formatCurrency(v)} />}
        />
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function TiposTreemap({ data }: { data: TreemapEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={350}>
        <Treemap
          data={data}
          dataKey="size"
          nameKey="name"
          content={<TreemapContent minWidth={35} minHeight={22} fontSize={10} valueFontSize={9} borderRadius={3} formatValue={(v) => formatCurrency(v)} />}
        />
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function TipoEstadoStackedChart({
  data,
  estados,
}: {
  data: TipoEstadoRow[];
  estados: string[];
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer
        width="100%"
        height={Math.max(320, data.length * 42)}
      >
        <BarChart accessibilityLayer data={data} layout="vertical" margin={{ left: 120 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis dataKey="tipo" type="category" width={110} tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v, name) => [formatNumber(v as number), name as string]} />
          <Legend />
          {estados.map((estado, idx) => (
            <Bar
              key={estado}
              dataKey={estado}
              name={estado}
              stackId="estado"
              fill={getSeriesColor(idx)}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
