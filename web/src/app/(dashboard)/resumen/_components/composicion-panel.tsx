"use client";

import { useMemo } from "react";
import { Panel, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { getEstadoChartColor } from "@/lib/chart-colors";
import { estadoLabel } from "@/lib/estados";
import { useFilters } from "@/lib/filters";
import { cn, formatNumber, formatPercent } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";
import { BarraApilada, tramosApilados } from "./contexto-graficos";

/**
 * Composición del ámbito — el desglose que el payload ya traía y nadie pintaba.
 *
 * `GET /analytics/overview` devuelve `por_estado` en la misma respuesta que
 * alimenta la tira de contexto, y el Resumen lo descartaba. La ficha de la
 * página en `lib/navigation.ts` seguía prometiendo «distribución por estado» —
 * describía una pantalla que había dejado de existir.
 *
 * Tuvo un segundo corte, «Por órgano», con los ocho órganos con más
 * expedientes. Se retiró (2026-10): repetía Mercado › Órganos, que es donde se
 * analizan, y sus filas no podían filtrar nada —el órgano no es una clave del
 * ámbito—. Lo que queda es el corte que sí hace algo en esta pantalla.
 *
 * Arriba, una barra apilada: dice de un vistazo cuánto del ámbito está
 * abierto y cuánto cerrado, que es lo que se pregunta al entrar. Debajo, una
 * fila por estado, de mayor a menor, con su propia barra: la apilada da la
 * parte de cada uno, las filas ordenan y comparan los pequeños, que en la
 * apilada son una raya. La barra de cada fila se mide contra el estado mayor,
 * no contra el total, así que el porcentaje del total va escrito a su lado.
 * Cada fila es un `<button>` de verdad, con foco y nombre accesible, que lleva
 * su recuento y su parte en texto: las barras no dicen nada que el texto no
 * diga.
 *
 * Cada estado **filtra el ámbito al pulsarlo**, que es la regla dura del
 * sistema de gráficos de la consola: clic en una marca filtra, no navega.
 */

const ALTO = 56;

/**
 * La barra de una fila, medida contra el estado mayor. Con un mínimo visible:
 * un estado con un puñado de expedientes sigue teniendo marca. Sin transición,
 * como la apilada.
 */
function BarraEstado({
  n,
  maximo,
  color,
  atenuado,
}: {
  n: number;
  maximo: number;
  color: string;
  atenuado: boolean;
}) {
  const ancho = maximo > 0 ? Math.max(1.5, (n / maximo) * 100) : 0;
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 8"
      preserveAspectRatio="none"
      className="h-2 w-full overflow-hidden rounded-sm"
    >
      <rect width="100" height="8" className="fill-muted/60" />
      <rect width={ancho} height="8" fill={color} className={cn(atenuado && "opacity-30")} />
    </svg>
  );
}

export function ComposicionPanel({ className }: { className?: string }) {
  const { estados, setEstados } = useFilters();

  const overview = useFilteredQuery<AnalyticsOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    // Misma consulta y mismas opciones que la tira de contexto: el fallo se
    // pinta en el panel, sin toast encima.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );

  const tramos = useMemo(
    () =>
      tramosApilados(
        [...(overview.data?.por_estado ?? [])]
          .sort((a, b) => b.n - a.n)
          .map((estado) => ({ estado: estado.estado, n: estado.n, color: getEstadoChartColor(estado.estado) })),
      ),
    [overview.data?.por_estado],
  );

  const alternarEstado = (codigo: string) => {
    setEstados(
      estados.includes(codigo)
        ? estados.filter((valor) => valor !== codigo)
        : [...estados, codigo],
    );
  };

  const totalEstado = tramos.reduce((suma, tramo) => suma + tramo.n, 0);
  const maximo = tramos.reduce((mayor, tramo) => Math.max(mayor, tramo.n), 0);

  return (
    <Panel className={className}>
      <PanelTitle
        title="Composición por estado"
        hint={
          totalEstado > 0
            ? `${formatNumber(totalEstado)} expedientes · pulsa un estado para filtrar el ámbito`
            : "pulsa un estado para filtrar el ámbito"
        }
        actions={
          estados.length > 0 ? (
            <Button type="button" variant="ghost" size="sm" onClick={() => setEstados([])}>
              Quitar filtro de estado
            </Button>
          ) : undefined
        }
      />

      {overview.error ? (
        // Sin esto, un fallo pintaba «Sin expedientes en el ámbito»: un vacío
        // falso que se lee como dato.
        <PanelError
          variant="inline"
          title="No se pudo cargar la composición"
          error={overview.error}
          onRetry={() => void overview.refetch()}
          height={ALTO}
        />
      ) : overview.isLoading ? (
        <PanelLoading height={ALTO} />
      ) : tramos.length === 0 ? (
        <PanelEmpty
          title="Sin expedientes en el ámbito"
          hint="Quita algún filtro del ámbito o amplía las fechas."
          height={ALTO}
        />
      ) : (
        <div className="flex min-h-[56px] flex-col gap-3">
          {/* Sin transición: al cambiar el ámbito la barra está ya en su valor.
              Un deslizamiento entre dos ámbitos se lee como que el dato cambió. */}
          <BarraApilada tramos={tramos} total={totalEstado} activos={estados} />
          <div
            role="group"
            aria-label="Filtrar el ámbito por estado"
            className="grid grid-cols-1 gap-x-6 gap-y-0.5 sm:grid-cols-2"
          >
            {tramos.map((tramo) => {
              const activo = estados.includes(tramo.estado);
              const atenuado = estados.length > 0 && !activo;
              return (
                <button
                  key={tramo.estado}
                  type="button"
                  aria-pressed={activo}
                  onClick={() => alternarEstado(tramo.estado)}
                  className={cn(
                    "-mx-1.5 grid h-8 grid-cols-[minmax(0,9rem)_minmax(0,1fr)_4.5rem_3.25rem] items-center gap-2.5 rounded-md px-1.5 text-left text-tf-meta transition-colors active:duration-0",
                    activo ? "bg-primary/10" : "hover:bg-primary/5 active:bg-primary/10",
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <svg aria-hidden="true" viewBox="0 0 8 8" className="h-2 w-2 flex-none">
                      <rect width="8" height="8" rx="2" fill={tramo.color} />
                    </svg>
                    <span className={cn("truncate", activo && "font-semibold")}>{estadoLabel(tramo.estado)}</span>
                  </span>
                  <BarraEstado n={tramo.n} maximo={maximo} color={tramo.color} atenuado={atenuado} />
                  <span className="tf-tnum text-right font-semibold">{formatNumber(tramo.n)}</span>
                  <span className="tf-tnum text-right text-muted-foreground">
                    {formatPercent((tramo.n / totalEstado) * 100)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </Panel>
  );
}
