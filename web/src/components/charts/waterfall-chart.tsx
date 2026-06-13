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
              return (
                <div className="rounded border border-border bg-popover px-3 py-2 text-sm text-popover-foreground shadow">
                  <p className="font-medium">{d.period}</p>
                  <p>
                    Delta:{" "}
                    <span className={d.isPositive ? "text-green-600" : "text-red-600"}>
                      {d.isPositive ? "+" : "-"}
                      {formatNumber(d.delta)}
                    </span>
                  </p>
                  <p>Acumulado: {formatNumber(d.cumulative)}</p>
                </div>
              );
            }}
          />
          <Bar dataKey="base" stackId="waterfall" fill="transparent" />
          <Bar dataKey="delta" stackId="waterfall">
            {transformed.map((entry, index) => (
              <Cell
                key={index}
                fill={entry.isPositive ? "hsl(142 71% 45%)" : "hsl(var(--destructive))"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
