"use client";

import { CalendarClock } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCurrency } from "@/lib/utils";
import type { Horizonte } from "../../_hooks/use-horizonte";

/**
 * Cartera en juego por empresa.
 *
 * El ranking es el del endpoint de resumen —los diez primeros de su lista, ya
 * ordenada en el servidor— y no un `groupBy` de las filas de la tabla. El
 * horizonte se rotula en la descripción porque el mismo gráfico dice cosas muy
 * distintas a 3 y a 24 meses.
 */
export function HorizonteCartera({
  meses,
  topCartera,
  isLoading,
}: {
  meses: string;
  topCartera: Horizonte["topCartera"];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cartera en juego por empresa</CardTitle>
        <CardDescription>
          Top 10 adjudicatarios por importe de contratos que vencen en {meses} meses.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[320px] w-full" />
        ) : topCartera.length === 0 ? (
          <EmptyState
            icon={CalendarClock}
            title="Sin vencimientos en la ventana"
            hint="Amplía el horizonte temporal para ver más contratos."
          />
        ) : (
          <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart accessibilityLayer data={topCartera} layout="vertical" margin={{ left: 120 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tickFormatter={(v: number) => formatCurrency(v)} fontSize={11} />
                <YAxis type="category" dataKey="empresa" width={120} fontSize={11} />
                <Tooltip formatter={(value) => [formatCurrency(Number(value ?? 0)), "Importe en juego"]} />
                <Bar dataKey="importe" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartErrorBoundary>
        )}
      </CardContent>
    </Card>
  );
}
