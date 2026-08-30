"use client";

import * as React from "react";
import {
  RadarChart as RechartsRadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Legend,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { cn } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";

interface RadarDataPoint {
  dimension: string;
  /**
   * `null` = esa dimensión no existe para esa serie, y Recharts deja el hueco.
   *
   * No es lo mismo que `0`. En un radar el 0 es el vértice pegado al centro,
   * que se lee como «el peor del mercado en esa dimensión»: rellenar un dato
   * ausente con 0 no es abstenerse, es afirmar lo contrario de lo que se sabe.
   */
  value: number | null;
  fullMark?: number;
}

interface RadarChartProps {
  data: RadarDataPoint[];
  name?: string;
  compareData?: RadarDataPoint[];
  compareName?: string;
  height?: number;
  className?: string;
}

export const RadarChart = React.memo(function RadarChart({
  data,
  name = "Valor",
  compareData,
  compareName = "Comparación",
  height = 350,
  className,
}: RadarChartProps) {
  const merged = React.useMemo(() => {
    return data.map((d, i) => ({
      dimension: d.dimension,
      value: d.value,
      fullMark: d.fullMark ?? 100,
      ...(compareData ? { compare: compareData[i]?.value ?? 0 } : {}),
    }));
  }, [data, compareData]);

  if (!data || data.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-8">Sin datos disponibles</p>;
  }

  return (
    <div role="img" aria-label="Gráfico de radar" className={cn("w-full", className)}>
      <ResponsiveContainer width="100%" height={height}>
        <RechartsRadarChart data={merged} cx="50%" cy="50%" outerRadius="80%">
          <PolarGrid stroke="hsl(var(--border))" />
          <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 12, fill: "hsl(var(--foreground))" }} />
          <PolarRadiusAxis tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} />
          <Radar
            name={name}
            dataKey="value"
            stroke="hsl(var(--primary))"
            fill="hsl(var(--primary))"
            fillOpacity={0.3}
          />
          {compareData && (
            <Radar
              name={compareName}
              dataKey="compare"
              stroke={CHART_SERIES[2]}
              fill={CHART_SERIES[2]}
              fillOpacity={0.2}
            />
          )}
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: "6px",
              color: "hsl(var(--popover-foreground))",
            }}
          />
          {compareData && <Legend />}
        </RechartsRadarChart>
      </ResponsiveContainer>
    </div>
  );
});
