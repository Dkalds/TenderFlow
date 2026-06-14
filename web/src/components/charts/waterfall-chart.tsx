"use client";

import * as React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils";
import { ChartTooltip } from "@/components/charts/chart-tooltip";

interface WaterfallPoint {
  period: string;
  delta: number;
  cumulative: number;
}

interface WaterfallChartProps {
  data: WaterfallPoint[];
  height?: number;
  className?: string;
}

interface TransformedPoint {
  period: string;
  base: number;
  delta: number;
  cumulative: number;
  isPositive: boolean;
}

export function WaterfallChart({ data, height = 300, className }: WaterfallChartProps) {
  const transformed = React.useMemo<TransformedPoint[]>(() => {
    if (!data || data.length === 0) return [];
    return data.map((d) => {
      const base = d.delta >= 0 ? d.cumulative - d.delta : d.cumulative;
      return {
        period: d.period,
        base: Math.max(0, base),
        delta: Math.abs(d.delta),
        cumulative: d.cumulative,
        isPositive: d.delta >= 0,
      };
    });
  }, [data]);

  if (!data || data.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-8">Sin datos disponibles</p>;
  }

  return (
    <div role="img" aria-label="Gráfico de cascada" className={cn("w-full", className)}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={transformed} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <XAxis dataKey="period" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatNumber(v)} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0]?.payload as TransformedPoint;
              const deltaColor = d.isPositive
                ? "hsl(var(--success))"
                : "hsl(var(--destructive))";
              return (
                <ChartTooltip
                  active
                  label={d.period}
                  payload={[
                    {
                      name: "Delta",
                      value: `${d.isPositive ? "+" : "-"}${formatNumber(d.delta)}`,
                      color: deltaColor,
                    },
                    {
                      name: "Acumulado",
                      value: formatNumber(d.cumulative),
                      color: "hsl(var(--muted-foreground))",
                    },
                  ]}
                />
              );
            }}
          />
          <Bar dataKey="base" stackId="waterfall" fill="transparent" />
          <Bar dataKey="delta" stackId="waterfall">
            {transformed.map((entry, index) => (
              <Cell
                key={index}
                fill={entry.isPositive ? "hsl(var(--success))" : "hsl(var(--destructive))"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
