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
  ScatterChart,
  Scatter,
  ZAxis,
  Label,
  LabelList,
  Treemap,
  Legend,
  Line,
  ComposedChart,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { TreemapContent } from "@/components/charts/treemap-content";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

export interface ScatterPoint {
  nombre: string;
  ticket_medio: number;
  n_organos: number;
}

interface BarEntry {
  nombre: string;
  count: number;
}

interface PieEntry {
  name: string;
  value: number;
}

interface TreemapEntry {
  name: string;
  size: number;
  count: number;
  [key: string]: string | number;
}

interface PositioningEntry {
  nombre: string;
  baja_media: number;
  importe_medio: number;
  count: number;
  pct_monopolio: number;
}

interface EstacionalidadEntry {
  mes: string;
  count: number;
  importe: number;
}

/* ── Exported chart components ─────────────────────────────────── */

export function CompetitorsBarChart({ data }: { data: BarEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={Math.max(400, data.length * 32)}>
        <BarChart data={data} layout="vertical" margin={{ left: 180 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 12 }} />
          <YAxis
            dataKey="nombre"
            type="category"
            tick={{ fontSize: 11 }}
            width={170}
            tickFormatter={(v: string) => truncate(v, 30)}
          />
          <Tooltip formatter={(v) => formatNumber(v as number)} />
          <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Adjudicaciones" />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function CompetitorsPieChart({ data }: { data: PieEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            outerRadius={140}
            label={({ name, percent }: { name?: string; percent?: number }) =>
              `${name ?? ""}: ${((percent ?? 0) * 100).toFixed(1)}%`
            }
            labelLine={{ strokeWidth: 1 }}
          >
            {data.map((_, idx) => (
              <Cell key={idx} fill={getSeriesColor(idx)} />
            ))}
          </Pie>
          <Tooltip formatter={(v) => formatCurrency(v as number)} />
        </PieChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function CompetitorsScatterChart({
  data,
  top5Names,
}: {
  data: ScatterPoint[];
  top5Names: Set<string>;
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            dataKey="ticket_medio"
            name="Ticket Medio"
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => formatCurrency(v)}
          >
            <Label value="Ticket Medio" position="bottom" offset={0} style={{ fontSize: 12 }} />
          </XAxis>
          <YAxis type="number" dataKey="n_organos" name="Organos" tick={{ fontSize: 11 }}>
            <Label value="N. Organos" angle={-90} position="left" offset={0} style={{ fontSize: 12 }} />
          </YAxis>
          <ZAxis range={[40, 400]} />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as ScatterPoint;
              return (
                <div className="rounded-md border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md">
                  <p className="font-medium">{d.nombre}</p>
                  <p>Ticket medio: {formatCurrency(d.ticket_medio)}</p>
                  <p>Organos: {formatNumber(d.n_organos)}</p>
                </div>
              );
            }}
          />
          <Scatter data={data} fill={CHART_SERIES[0]} fillOpacity={0.7}>
            <LabelList
              dataKey="nombre"
              position="top"
              style={{ fontSize: 12 }}
              content={({ x, y, value }) => {
                if (!top5Names.has(value as string)) return null;
                return (
                  <text
                    x={x as number}
                    y={(y as number) - 8}
                    textAnchor="middle"
                    fontSize={12}
                    fill="hsl(var(--foreground))"
                  >
                    {truncate(value as string, 18)}
                  </text>
                );
              }}
            />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function CompetitorsTreemap({ data }: { data: TreemapEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <Treemap
          data={data}
          dataKey="size"
          nameKey="name"
          aspectRatio={4 / 3}
          stroke="hsl(var(--border))"
          content={
            <TreemapContent
              minWidth={50}
              minHeight={30}
              fontSize={11}
              valueFontSize={10}
              borderRadius={2}
              opacity={1}
              formatValue={(v) => formatCurrency(v)}
            />
          }
        >
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div className="rounded-md border bg-popover px-3 py-2 text-sm shadow-md">
                  <p className="font-medium">{d.name}</p>
                  <p>Importe: {formatCurrency(d.size)}</p>
                  <p>Adjudicaciones: {formatNumber(d.count)}</p>
                </div>
              );
            }}
          />
        </Treemap>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function CompetitorsPositioningChart({ data }: { data: PositioningEntry[] }) {
  const top5Names = new Set(
    [...data].sort((a, b) => b.count - a.count).slice(0, 5).map((d) => d.nombre),
  );

  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={400}>
        <ScatterChart margin={{ top: 20, right: 20, bottom: 30, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            dataKey="baja_media"
            name="Baja Media"
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          >
            <Label value="Baja Media %" position="bottom" offset={10} style={{ fontSize: 12 }} />
          </XAxis>
          <YAxis
            type="number"
            dataKey="importe_medio"
            name="Importe Medio"
            tick={{ fontSize: 11 }}
            scale="log"
            domain={["auto", "auto"]}
            tickFormatter={(v: number) => formatCurrency(v)}
          >
            <Label
              value="Importe Medio (log)"
              angle={-90}
              position="left"
              offset={0}
              style={{ fontSize: 12 }}
            />
          </YAxis>
          <ZAxis dataKey="count" range={[40, 600]} name="Contratos" />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as PositioningEntry;
              return (
                <div className="rounded-md border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md">
                  <p className="font-medium">{d.nombre}</p>
                  <p>Baja media: {d.baja_media.toFixed(1)}%</p>
                  <p>Importe medio: {formatCurrency(d.importe_medio)}</p>
                  <p>Contratos: {formatNumber(d.count)}</p>
                  <p>% Monopolio: {d.pct_monopolio.toFixed(1)}%</p>
                </div>
              );
            }}
          />
          <Scatter data={data} fill={CHART_SERIES[2]} fillOpacity={0.7}>
            <LabelList
              dataKey="nombre"
              position="top"
              content={({ x, y, value }) => {
                if (!top5Names.has(value as string)) return null;
                return (
                  <text
                    x={x as number}
                    y={(y as number) - 8}
                    textAnchor="middle"
                    fontSize={10}
                    fill="hsl(var(--foreground))"
                  >
                    {truncate(value as string, 18)}
                  </text>
                );
              }}
            />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

export function CompetitorsEstacionalidadChart({ data }: { data: EstacionalidadEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="mes" tick={{ fontSize: 12 }} />
          <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => formatCurrency(v)}
          />
          <Tooltip
            formatter={(v, name) =>
              name === "Importe"
                ? formatCurrency(Number(v ?? 0))
                : formatNumber(Number(v ?? 0))
            }
          />
          <Legend />
          <Bar
            yAxisId="left"
            dataKey="count"
            fill={CHART_SERIES[0]}
            radius={[4, 4, 0, 0]}
            name="Adjudicaciones"
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="importe"
            stroke={CHART_SERIES[1]}
            strokeWidth={2}
            dot={{ r: 3 }}
            name="Importe"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
