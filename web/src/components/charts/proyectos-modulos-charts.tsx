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
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

/** Una barra: una familia de la taxonomía o un módulo SAP, y sus licitaciones. */
interface CategoriaBarEntry {
  nombre: string;
  count: number;
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

/**
 * Licitaciones por categoría, en barras horizontales. Lo usan las familias
 * (nombres largos: «Infraestructura, cloud y redes») y los módulos SAP (cortos:
 * «FI»), así que el ancho del eje sale del nombre más largo.
 */
export function CategoriasBarChart({ data }: { data: CategoriaBarEntry[] }) {
  const ancho = Math.min(200, Math.max(60, ...data.map((d) => d.nombre.length * 6.5)));
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer
        width="100%"
        height={Math.max(300, data.length * 30)}
      >
        <BarChart accessibilityLayer
          data={data}
          layout="vertical"
          margin={{ left: 8 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            className="stroke-border"
          />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis
            dataKey="nombre"
            type="category"
            width={ancho}
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
              `${name ?? ""} (${formatPercent((percent ?? 0) * 100)})`
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

/** Importe por categoría (familia, módulo o tipo de proyecto), en treemap. */
export function ImporteTreemap({ data }: { data: TreemapEntry[] }) {
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
