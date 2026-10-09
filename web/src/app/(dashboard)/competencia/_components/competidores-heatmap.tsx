"use client";

/**
 * Dónde gana cada uno: la matriz empresa × CCAA.
 *
 * Cada cabecera de columna es un filtro: pulsar una CCAA la añade o la quita
 * del ámbito global, así que el resto de la pantalla la sigue. Vivía en la
 * cuarta de nueve pestañas; es el único corte que además de enseñar filtra, y
 * por eso tiene panel propio.
 *
 * Es una tabla de verdad —cabeceras de fila y de columna— y la intensidad va en
 * cinco pasos de clase, sin `style` en línea.
 */

import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Pista } from "@/components/ui/pista";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatNumber } from "@/lib/utils";

import { pasoIntensidad } from "../_hooks/casillas-ccaa";
import type { HeatmapModel } from "../_hooks/competidores-cruces";

/** Alto reservado para carga y vacío: diez filas y su cabecera. */
const ALTO = 300;

/** Clase de cada paso de intensidad; el más alto invierte el texto. */
const PASO = [
  "",
  "bg-primary/10",
  "bg-primary/20",
  "bg-primary/35",
  "bg-primary/50",
  "bg-primary/90 text-primary-foreground",
];

export function CompetidoresHeatmap({
  heatmap,
  activeCcaa,
  onToggleCcaa,
  filtrado,
  isLoading,
}: {
  heatmap: HeatmapModel;
  /** CCAAs del ámbito global activo: las cabeceras encendidas. */
  activeCcaa: Set<string>;
  onToggleCcaa: (ccaa: string) => void;
  /** Hay búsqueda local activa: el panel se marca como filtrado. */
  filtrado: boolean;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        title="Dónde gana cada uno"
        hint="adjudicaciones por comunidad · pulsa una cabecera para filtrar el ámbito"
        actions={
          filtrado ? (
            <Badge variant="neutral" size="sm">
              Filtrado
            </Badge>
          ) : null
        }
      />
      {isLoading ? (
        <PanelLoading height={ALTO} />
      ) : heatmap.empresas.length === 0 ? (
        <PanelEmpty
          title="Sin adjudicaciones por comunidad"
          hint="Ningún competidor con adjudicaciones en el ámbito actual o con esa búsqueda."
          height={ALTO}
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] table-fixed border-separate border-spacing-0.5 text-tf-micro">
              <caption className="sr-only">Adjudicaciones de cada empresa por comunidad autónoma</caption>
              <thead>
                <tr>
                  <th scope="col" className="w-40 p-1 text-left font-medium text-muted-foreground">
                    <span className="sr-only">Empresa</span>
                  </th>
                  {heatmap.ccaas.map((ccaa) => {
                    const activa = activeCcaa.has(ccaa);
                    return (
                      <th key={ccaa} scope="col" className="p-0 font-medium">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              onClick={() => onToggleCcaa(ccaa)}
                              aria-pressed={activa}
                              aria-label={`Filtrar por ${ccaa}`}
                              className={cn(
                                "block w-full cursor-pointer truncate rounded-sm px-0.5 py-1 text-center transition-colors hover:bg-primary/5",
                                activa ? "bg-primary/10 text-primary" : "text-muted-foreground",
                              )}
                            >
                              {ccaa}
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>{activa ? `Quitar ${ccaa} del ámbito` : `Filtrar por ${ccaa}`}</TooltipContent>
                        </Tooltip>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {heatmap.empresas.map((empresa) => (
                  <tr key={empresa}>
                    {/* El nombre va entero en el DOM y lo recorta el CSS: el
                        lector lo lee completo y la `Pista` lo enseña al pasar
                        el puntero, sin añadir paradas de tabulación. */}
                    <th scope="row" className="p-1 text-left font-medium">
                      <Pista contenido={empresa}>
                        <span className="block truncate">{empresa}</span>
                      </Pista>
                    </th>
                    {heatmap.ccaas.map((ccaa) => {
                      const valor = heatmap.matrix[empresa]?.[ccaa];
                      return (
                        <td key={ccaa} className="p-0">
                          <Pista
                            contenido={
                              valor
                                ? `${empresa} · ${ccaa}: ${formatNumber(valor)} adjudicaciones`
                                : `${empresa} · ${ccaa}: sin adjudicaciones`
                            }
                          >
                            <span
                              className={cn(
                                "tf-tnum block h-6 cursor-default rounded-sm text-center leading-6",
                                PASO[pasoIntensidad(valor ?? 0, heatmap.max)],
                              )}
                            >
                              {valor ? formatNumber(valor) : ""}
                            </span>
                          </Pista>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2.5 text-tf-meta text-muted-foreground">
            Las {formatNumber(heatmap.empresas.length)} empresas con más adjudicaciones. Un hueco es una comunidad donde
            esa empresa no ha ganado nada en el ámbito.
          </p>
        </>
      )}
    </Panel>
  );
}
