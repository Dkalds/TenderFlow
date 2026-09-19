"use client";

/**
 * Mapa de calor tecnología × órgano.
 *
 * Es una rejilla CSS y no un gráfico: la matriz llega ya cruzada del backend
 * (`cross_organo`) y lo único que se hace aquí es pintar la intensidad. El
 * valor 0 se deja en blanco a propósito — un «0» en cada celda vacía convierte
 * la rejilla en ruido y no añade información que el color no dé.
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Grid3x3 } from "lucide-react";
import { Pista } from "@/components/ui/pista";

import type { HeatmapMatrix } from "../_hooks/use-tecnologias-view";

function heatColor(value: number, max: number): string {
  if (value === 0 || max === 0) return "hsl(var(--muted) / 0.4)";
  const alpha = 0.12 + (value / max) * 0.83;
  return `hsl(var(--primary) / ${alpha})`;
}

export function TecnologiasHeatmap({ heatmap }: { heatmap: HeatmapMatrix }) {
  const columnas = {
    gridTemplateColumns: `140px repeat(${heatmap.organos.length}, minmax(80px, 1fr))`,
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Grid3x3 className="h-4 w-4" />
          Top órganos por tecnología
        </CardTitle>
        <CardDescription>Nº de licitaciones</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <div className="inline-block min-w-full">
            <div className="grid gap-px" style={columnas}>
              <div className="p-1" />
              {/* Cabeceras y celdas con `Pista` y no con un disparador
                  focusable: la rejilla no gana paradas de tabulación. El
                  órgano va entero en el DOM y lo recorta el CSS. */}
              {heatmap.organos.map((org) => (
                <Pista key={org} contenido={org}>
                  <div className="truncate p-1 text-center text-xs font-medium text-muted-foreground">{org}</div>
                </Pista>
              ))}
            </div>
            {heatmap.techs.map((tech) => (
              <div key={tech} className="grid gap-px" style={columnas}>
                <Pista contenido={tech}>
                  <div className="truncate p-1 text-xs font-medium">{tech}</div>
                </Pista>
                {heatmap.organos.map((org) => {
                  const val = heatmap.cell.get(`${tech}||${org}`) ?? 0;
                  return (
                    <Pista key={org} contenido={`${tech} x ${org}: ${val}`}>
                      <div
                        className="flex items-center justify-center rounded p-1 text-xs tabular-nums"
                        style={{
                          backgroundColor: heatColor(val, heatmap.maxVal),
                          color: val > heatmap.maxVal * 0.5 ? "hsl(var(--primary-foreground))" : "inherit",
                        }}
                      >
                        {val > 0 ? val : ""}
                      </div>
                    </Pista>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
