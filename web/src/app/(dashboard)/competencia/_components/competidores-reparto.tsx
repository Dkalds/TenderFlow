"use client";

/**
 * El reparto del mercado en una barra al 100 %: las primeras empresas con su
 * nombre y el resto en un solo tramo.
 *
 * Sustituye a la tarta y al treemap, que dibujaban la misma columna de cuota de
 * dos maneras. Una barra se lee de izquierda a derecha y deja comparar tramos
 * contiguos; en una tarta de once porciones eso no se ve.
 *
 * La barra es el dibujo; la leyenda de debajo es la lista real, con un botón
 * por empresa: el teclado y el lector de pantalla recorren ahí lo que la barra
 * solo ofrece al ratón.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, formatPercent } from "@/lib/utils";

import type { TramoReparto } from "../_hooks/competidores-series";
import type { Metrica } from "../_hooks/competidores-types";
import { Muestra } from "./dibujos";

/** Índice de `chart-8`, reservado para el resto del mercado. */
const INDICE_OTROS = 7;

/** Color de serie de un tramo con nombre, saltándose el reservado a «Otras». */
function colorDe(tramo: TramoReparto, indice: number): string {
  if (tramo.esOtros) return CHART_SERIES[INDICE_OTROS];
  return CHART_SERIES[indice < INDICE_OTROS ? indice : indice + 1];
}

/** Hueco entre tramos, en unidades del viewBox (de 100). */
const HUECO = 0.25;

export function CompetidoresReparto({
  tramos,
  metrica,
  isLoading,
  onEmpresaClick,
}: {
  tramos: TramoReparto[];
  metrica: Metrica;
  isLoading: boolean;
  onEmpresaClick: (nombre: string) => void;
}) {
  const medida = metrica === "importe" ? "del importe adjudicado" : "de las adjudicaciones";
  // Dónde empieza cada tramo: la suma de los anteriores.
  const inicios = tramos.map((_, i) => tramos.slice(0, i).reduce((suma, t) => suma + t.pct, 0));
  return (
    <Panel>
      <PanelTitle
        title="Reparto del mercado"
        hint={`cuota ${medida} · las primeras y el resto · pulsa una para abrir su perfil`}
      />
      {isLoading ? (
        <Skeleton className="h-[4.25rem] w-full" />
      ) : tramos.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Sin reparto que dibujar"
          hint="Ningún competidor con adjudicaciones en el ámbito actual. Amplía las fechas o quita filtros."
        />
      ) : (
        <>
          <svg aria-hidden="true" className="h-9 w-full rounded-md" viewBox="0 0 100 12" preserveAspectRatio="none">
            {tramos.map((tramo, i) => {
              const inicio = inicios[i];
              const ancho = Math.max(0, tramo.pct - HUECO);
              return (
                <g key={tramo.nombre}>
                  <rect
                    x={inicio}
                    y="0"
                    width={ancho}
                    height="9.5"
                    fill={colorDe(tramo, i)}
                    className={tramo.esOtros ? undefined : "cursor-pointer"}
                    onClick={tramo.esOtros ? undefined : () => onEmpresaClick(tramo.nombre)}
                  />
                  {/* La abierta se subraya: el color ya lo usa la serie. */}
                  {tramo.seleccionado && (
                    <rect x={inicio} y="10.5" width={ancho} height="1.5" fill="hsl(var(--foreground))" />
                  )}
                </g>
              );
            })}
          </svg>
          <ul aria-label="Reparto del mercado" className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
            {tramos.map((tramo, i) => (
              <li key={tramo.nombre} className="flex min-w-0 max-w-full items-center gap-1.5 text-tf-meta">
                <Muestra color={colorDe(tramo, i)} />
                {tramo.esOtros ? (
                  <span className="truncate text-muted-foreground">{tramo.nombre}</span>
                ) : (
                  <Pista contenido={tramo.nombre}>
                    <button
                      type="button"
                      aria-pressed={tramo.seleccionado}
                      onClick={() => onEmpresaClick(tramo.nombre)}
                      className={cn(
                        "max-w-[11rem] cursor-pointer truncate text-left transition-colors hover:text-primary",
                        tramo.seleccionado ? "font-semibold text-primary" : "font-medium",
                      )}
                    >
                      {tramo.nombre}
                    </button>
                  </Pista>
                )}
                <span className="tf-tnum flex-none font-semibold">{formatPercent(tramo.pct)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
