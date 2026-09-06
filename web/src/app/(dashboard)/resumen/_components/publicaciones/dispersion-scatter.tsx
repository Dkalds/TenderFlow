"use client";

/**
 * Dispersión — fecha × importe sobre la muestra repartida.
 *
 * La nube se conserva (consolidar no elimina funcionalidad) con dos arreglos
 * que la hacen legible: eje **logarítmico** y muestra repartida por toda la
 * ventana. El pie declara los dos denominadores que la cifra necesita —cuántos
 * puntos de cuántas publicaciones, y cuántos expedientes quedan fuera por no
 * declarar importe, que un eje log no puede dibujar.
 */

import { useRouter } from "next/navigation";
import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PanelEmpty } from "@/components/console/panel";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { estadoLabel } from "@/lib/estados";
import { formatCompactCurrency, formatCurrency, formatDate, formatNumber, truncate } from "@/lib/utils";
import { TIMELINE_MAX } from "../types";
import { ALTO, type PuntoScatter } from "./publicaciones-data";

export interface DispersionScatterProps {
  puntos: PuntoScatter[];
  /** Estados presentes, con su color: la leyenda de debajo del gráfico. */
  leyenda: [string, string][];
  muestreado: boolean;
  /** Publicaciones de la ventana según el endpoint: el denominador del pie. */
  totalVentana: number;
  sinImporte: number;
  ventana: string;
}

export function DispersionScatter({
  puntos,
  leyenda,
  muestreado,
  totalVentana,
  sinImporte,
  ventana,
}: DispersionScatterProps) {
  const router = useRouter();

  if (puntos.length === 0) {
    return <PanelEmpty message="Sin publicaciones con importe en la ventana." height={ALTO} />;
  }

  return (
    <>
      <ChartErrorBoundary>
        <ResponsiveContainer width="100%" height={ALTO}>
          <ScatterChart accessibilityLayer margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis
              dataKey="x"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value: number) => formatDate(new Date(value))}
              tick={{ fontSize: 10 }}
              name="Fecha"
            />
            {/* Logarítmico: con el 71 % de los importes por debajo de 1.000 €
                y máximos de 16 M, la escala lineal dejaba la nube entera
                aplastada contra el eje. */}
            <YAxis
              dataKey="y"
              type="number"
              scale="log"
              // `dataMin`/`dataMax` y no `auto`: con `auto`, recharts añade
              // un tick de 0 € a un eje logarítmico, donde el cero no
              // existe.
              domain={["dataMin", "dataMax"]}
              allowDataOverflow
              tickFormatter={(value: number) => formatCompactCurrency(value)}
              tick={{ fontSize: 10 }}
              name="Importe"
              width={64}
            />
            <Tooltip
              content={({ payload }) => {
                if (!payload?.[0]) return null;
                const punto = payload[0].payload as PuntoScatter;
                return (
                  <div className="border-border bg-popover rounded-md border p-2 text-xs shadow">
                    <p className="font-medium">{truncate(punto.titulo, 50)}</p>
                    <p className="tf-tnum font-mono">{formatCurrency(punto.y)}</p>
                    <p className="text-muted-foreground">{estadoLabel(punto.estado)}</p>
                  </div>
                );
              }}
            />
            <Scatter
              data={puntos}
              shape="circle"
              legendType="none"
              className="cursor-pointer"
              onClick={(punto: unknown) => {
                const nodo = punto as { id?: string; payload?: { id?: string } } | undefined;
                const id = nodo?.id ?? nodo?.payload?.id;
                if (id) router.push(`/detalle?lic=${encodeURIComponent(id)}`);
              }}
            >
              {puntos.map((entrada) => (
                <Cell key={entrada.id} fill={entrada.fill} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </ChartErrorBoundary>

      <ul className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {leyenda.map(([codigo, color]) => (
          <li key={codigo} className="flex items-center gap-1.5">
            <span
              className="h-2 w-2 flex-none rounded-full"
              style={{ background: color }}
              aria-hidden="true"
            />
            <span className="text-muted-foreground text-[10.5px]">{estadoLabel(codigo)}</span>
          </li>
        ))}
      </ul>

      <p className="text-muted-foreground mt-2 text-[10.5px] leading-[1.45]">
        {muestreado ? (
          <>
            Muestra de <strong className="font-semibold">{formatNumber(puntos.length)}</strong> de{" "}
            {formatNumber(totalVentana)} publicaciones, repartida por toda la ventana {ventana}: el
            endpoint dibuja como mucho {formatNumber(TIMELINE_MAX)} puntos, y se toma uno de cada N
            en vez de sólo los más recientes.
          </>
        ) : (
          <>
            Las {formatNumber(totalVentana || puntos.length)} publicaciones {ventana}, sin
            recortar.
          </>
        )}
        {sinImporte > 0
          ? ` ${formatNumber(sinImporte)} no declaran importe y una escala logarítmica no puede dibujarlos.`
          : ""}
      </p>
    </>
  );
}
