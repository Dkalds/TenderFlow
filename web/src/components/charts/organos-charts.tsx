"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Treemap,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { TreemapContent } from "@/components/charts/treemap-content";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

interface RankingEntry {
  organo_contratacion: string;
  count: number;
  importe: number;
}

interface TreemapEntry {
  name: string;
  size?: number;
  children?: { name: string; size: number }[];
  [key: string]: unknown;
}

interface AdjudicatarioEntry {
  nombre: string;
  count: number;
  importe: number;
}

interface EstacionalidadEntry {
  mes_numero: number;
  count: number;
}

const MONTH_LABELS = [
  "Ene", "Feb", "Mar", "Abr", "May", "Jun",
  "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
];

/* ── Ranking bar chart (reused for top-by-count and top-by-importe) ── */

interface OrganosRankingChartProps {
  data: RankingEntry[];
  dataKey: "count" | "importe";
  fill: string;
  tooltipLabel: string;
  formatValue: (v: number) => string;
  onBarClick: (organo: string) => void;
}

export function OrganosRankingChart({
  data,
  dataKey,
  fill,
  tooltipLabel,
  formatValue,
  onBarClick,
}: OrganosRankingChartProps) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(400, data.length * 28)}>
        <BarChart accessibilityLayer data={data} layout="vertical" margin={{ left: 200 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            tick={{ fontSize: 12 }}
            tickFormatter={dataKey === "importe" ? (v: number) => formatCurrency(v) : undefined}
          />
          <YAxis
            dataKey="organo_contratacion"
            type="category"
            width={200}
            tick={{ fontSize: 12 }}
            tickFormatter={(v: string) => (v.length > 35 ? v.slice(0, 35) + "..." : v)}
          />
          <Tooltip
            formatter={(value) => [formatValue(value as number), tooltipLabel]}
            labelFormatter={(label) => label}
          />
          <Bar
            dataKey={dataKey}
            fill={fill}
            radius={[0, 4, 4, 0]}
            className="cursor-pointer"
            onClick={(_data, idx) => {
              if (data[idx]) onBarClick(data[idx].organo_contratacion);
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

/* ── Treemap ───────────────────────────────────────────────────── */

export function OrganosTreemapChart({ data }: { data: TreemapEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <Treemap
          data={data}
          dataKey="size"
          nameKey="name"
          content={<TreemapContent formatValue={(v) => formatCurrency(v)} />}
        />
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

/* ── Detail sheet: top adjudicatarios ──────────────────────────── */

export function OrganosAdjudicatariosChart({ data }: { data: AdjudicatarioEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart accessibilityLayer data={data.slice(0, 10).reverse()} layout="vertical" margin={{ left: 120 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatCurrency(v)} />
          <YAxis
            dataKey="nombre"
            type="category"
            width={120}
            tick={{ fontSize: 11 }}
            tickFormatter={(v: string) => (v.length > 18 ? v.slice(0, 18) + "…" : v)}
          />
          <Tooltip
            formatter={(value) => [formatCurrency(value as number), "Importe"]}
            labelFormatter={(label) => label}
          />
          <Bar dataKey="importe" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

/* ── Detail sheet: estacionalidad mensual ──────────────────────── */

export function OrganosEstacionalidadChart({ data }: { data: EstacionalidadEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart accessibilityLayer data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            dataKey="mes_numero"
            tick={{ fontSize: 12 }}
            tickFormatter={(m: number) => MONTH_LABELS[m - 1] ?? String(m)}
          />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip
            labelFormatter={(m) => MONTH_LABELS[(m as number) - 1] ?? String(m)}
            formatter={(v) => [formatNumber(v as number), "Licitaciones"]}
          />
          <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
