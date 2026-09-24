"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCurrency } from "@/lib/utils";
import type { Renovaciones } from "../../_hooks/use-renovaciones";

/** Alto del gráfico, y el mismo que gastan el esqueleto y el vacío: así la
 *  página no salta cuando llega el dato ni cuando resulta que no hay. */
const ALTO = 320;

/**
 * Cartera en juego por empresa.
 *
 * El ranking es el del endpoint de resumen —los diez primeros de su lista, ya
 * ordenada en el servidor— y no un `groupBy` de las filas de la tabla. El
 * horizonte se rotula en la cabecera porque el mismo gráfico dice cosas muy
 * distintas a 3 y a 24 meses.
 */
export function RenovacionesCartera({
  meses,
  topCartera,
  isLoading,
}: {
  meses: string;
  topCartera: Renovaciones["topCartera"];
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        title="Cartera en juego por empresa"
        hint={`Top 10 por importe que vence en ${meses} meses`}
      />
      {isLoading ? (
        <PanelLoading height={ALTO} />
      ) : topCartera.length === 0 ? (
        <PanelEmpty
          message="Ningún contrato vence en esta ventana. Amplía el horizonte para ver más."
          height={ALTO}
        />
      ) : (
        <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={ALTO}>
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
    </Panel>
  );
}
