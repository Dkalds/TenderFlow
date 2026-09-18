"use client";

/**
 * Mapa de calor empresa × CCAA. Cada cabecera de columna es un filtro: pulsar
 * una CCAA la añade o la quita del ámbito global, así que el resto de la
 * pantalla la sigue.
 */

import React from "react";

import { Pista } from "@/components/ui/pista";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { truncate } from "@/lib/utils";

import type { HeatmapModel } from "../_hooks/competidores-series";

function heatColor(value: number, max: number): string {
  if (max === 0) return "transparent";
  const intensity = value / max;
  const alpha = Math.max(0.08, intensity);
  return `hsl(var(--primary) / ${alpha})`;
}

export function CompetidoresHeatmap({
  heatmap,
  activeCcaa,
  onToggleCcaa,
}: {
  heatmap: HeatmapModel;
  /** CCAAs del ámbito global activo: las cabeceras encendidas. */
  activeCcaa: Set<string>;
  onToggleCcaa: (ccaa: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <div
        className="grid gap-px text-xs"
        style={{
          gridTemplateColumns: `180px repeat(${heatmap.ccaas.length}, minmax(50px, 1fr))`,
        }}
      >
        {/* Header row */}
        <div className="text-muted-foreground p-1 font-medium" />
        {heatmap.ccaas.map((ccaa) => (
          <Tooltip key={ccaa}>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => onToggleCcaa(ccaa)}
                aria-pressed={activeCcaa.has(ccaa)}
                aria-label={`Filtrar por ${ccaa}`}
                className={`hover:bg-muted cursor-pointer truncate rounded-sm p-1 text-center font-medium transition-colors ${activeCcaa.has(ccaa) ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
              >
                {truncate(ccaa, 10)}
              </button>
            </TooltipTrigger>
            <TooltipContent>{`Filtrar por ${ccaa}`}</TooltipContent>
          </Tooltip>
        ))}
        {/* Data rows */}
        {heatmap.empresas.map((empresa) => (
          <React.Fragment key={empresa}>
            {/* El nombre va entero en el DOM y lo recorta el CSS: el lector
                lo lee completo y la `Pista` lo enseña al pasar el puntero,
                sin añadir paradas de tabulación a la rejilla. */}
            <Pista contenido={empresa}>
              <div className="truncate p-1 font-medium">{empresa}</div>
            </Pista>
            {heatmap.ccaas.map((ccaa) => {
              const val = heatmap.matrix[empresa]?.[ccaa] ?? 0;
              return (
                <Pista key={`${empresa}-${ccaa}`} contenido={`${empresa} - ${ccaa}: ${val}`}>
                  <div
                    className="cursor-default rounded-sm p-1 text-center transition-colors"
                    style={{ backgroundColor: heatColor(val, heatmap.max) }}
                  >
                    {val > 0 ? val : ""}
                  </div>
                </Pista>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
