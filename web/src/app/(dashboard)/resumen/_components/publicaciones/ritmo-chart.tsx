"use client";

/**
 * Ritmo — publicaciones por día.
 *
 * Es lo que la nube de puntos no podía enseñar: el mercado publica a tirones
 * (3 expedientes un sábado, 1.082 el martes siguiente), y eso decide cuándo
 * mirar. La serie llega agregada del backend sobre el periodo **completo**, así
 * que el pie puede declarar el universo sin estimarlo aquí.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PanelEmpty } from "@/components/console/panel";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCompactCurrency, formatDate, formatNumber } from "@/lib/utils";
import type { TrendPoint } from "@/lib/api-types";
import { ALTO } from "./publicaciones-data";

export interface RitmoChartProps {
  serie: TrendPoint[];
  /** La serie llegó al techo de puntos del endpoint: hay días sin dibujar. */
  serieTruncada: boolean;
  ventana: string;
  onDia: (dia: string) => void;
}

export function RitmoChart({ serie, serieTruncada, ventana, onDia }: RitmoChartProps) {
  if (serie.length === 0) {
    return <PanelEmpty message="Sin publicaciones en la ventana seleccionada." height={ALTO} />;
  }

  const total = serie.reduce((suma, punto) => suma + punto.count, 0);

  return (
    <>
      <ChartErrorBoundary>
        <ResponsiveContainer width="100%" height={ALTO}>
          <BarChart accessibilityLayer data={serie} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
            <XAxis
              dataKey="period"
              tickFormatter={(value: string) => formatDate(value)}
              tick={{ fontSize: 10 }}
              interval="preserveStartEnd"
              minTickGap={24}
            />
            <YAxis
              tickFormatter={(value: number) => formatNumber(value)}
              tick={{ fontSize: 10 }}
              width={52}
            />
            <Tooltip
              cursor={{ fill: "hsl(var(--muted-foreground) / 0.08)" }}
              content={({ payload }) => {
                const punto = payload?.[0]?.payload as TrendPoint | undefined;
                if (!punto) return null;
                return (
                  <div className="border-border bg-popover rounded-md border p-2 text-xs shadow">
                    <p className="font-medium">{formatDate(punto.period)}</p>
                    <p className="tf-tnum font-mono">
                      {formatNumber(punto.count)} publicaciones
                    </p>
                    <p className="text-muted-foreground tf-tnum font-mono">
                      {formatCompactCurrency(punto.importe)}
                    </p>
                  </div>
                );
              }}
            />
            {/* Clic en una marca filtra el ámbito, no navega: regla dura
                del sistema de gráficos de la consola. */}
            <Bar
              dataKey="count"
              fill={CHART_SERIES[0]}
              radius={[2, 2, 0, 0]}
              className="cursor-pointer"
              onClick={(punto: unknown) => {
                const nodo = punto as { period?: string; payload?: { period?: string } };
                const dia = nodo?.period ?? nodo?.payload?.period;
                if (dia) onDia(dia);
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </ChartErrorBoundary>
      <p className="text-muted-foreground mt-2 text-[10.5px] leading-[1.45]">
        {formatNumber(total)} publicaciones {ventana}, en {serie.length} días con actividad,
        agregadas en backend sobre el periodo completo.
        {serieTruncada
          ? " La serie llegó al techo de puntos del endpoint: hay días sin dibujar."
          : ""}
      </p>
    </>
  );
}
