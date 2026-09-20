"use client";

/**
 * Heatmap Mes × Estado de Tendencias.
 *
 * Cada celda es el cruce REAL que calcula el backend (`GROUP BY mes, estado`
 * en `/analytics/trends`), no el producto de marginales que se pintaba antes
 * con el badge «Estimado» (RFC ux-tendencias #1, ADR-014).
 *
 * Drill-down (RFC #3): cada celda con licitaciones enlaza al listado de ese mes
 * y ese estado, y la cabecera de cada mes al listado del mes entero. Las
 * celdas no son paradas de tabulación (serían meses × estados); las cabeceras
 * sí, y son el camino de teclado.
 */

import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { estadoLabel } from "@/lib/estados";
import { useScopedHref } from "@/lib/filters";
import { cn } from "@/lib/utils";

import { mesHref, type HeatmapMesEstado } from "../_hooks/use-tendencias-view";

/**
 * Heatmap intensity — returns an inline style using the primary accent token
 * with variable alpha, so the scale lives in one place and respects the theme.
 */
function heatmapCellStyle(value: number, max: number): { backgroundColor: string } {
  if (max === 0 || value === 0) {
    return { backgroundColor: "hsl(var(--muted) / 0.4)" };
  }
  const alpha = 0.12 + (value / max) * 0.83;
  return { backgroundColor: `hsl(var(--primary) / ${alpha})` };
}

/** 7-step legend swatches mirroring the cell scale above. */
const HEATMAP_LEGEND_STEPS = [0, 0.16, 0.32, 0.48, 0.64, 0.8, 0.95] as const;

export function TendenciasHeatmap({
  heatmapData,
  isLoading,
}: {
  heatmapData: HeatmapMesEstado | null;
  isLoading: boolean;
}) {
  const scopedHref = useScopedHref();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Heatmap: Mes x Estado</CardTitle>
        <CardDescription>
          Licitaciones publicadas cada mes, por estado actual. Pulsa un mes o una
          celda para ver esas licitaciones.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[300px] w-full" />
        ) : heatmapData && heatmapData.meses.length > 0 && heatmapData.estados.length > 0 ? (
          <div className="overflow-x-auto">
            <div className="inline-block min-w-full">
              <div className="flex">
                <div className="w-32 shrink-0" />
                {heatmapData.meses.map((mes) => (
                  <Link
                    key={mes}
                    href={scopedHref(mesHref(mes))}
                    aria-label={`Ver licitaciones publicadas en ${mes}`}
                    className="w-14 shrink-0 truncate rounded-sm px-0.5 text-center text-xs text-muted-foreground hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {mes.length > 7 ? mes.slice(5) : mes}
                  </Link>
                ))}
              </div>
              {heatmapData.estados.map((estado) => (
                <div key={estado} className="flex items-center">
                  {/* `col` viaja con el código de la columna, no con la
                      etiqueta: sin traducir, la fila del heatmap se rotula "AGR". */}
                  <Pista contenido={estadoLabel(estado)}>
                    <div className="w-32 shrink-0 text-xs text-muted-foreground truncate pr-2">{estadoLabel(estado)}</div>
                  </Pista>
                  {heatmapData.meses.map((mes) => {
                    const value = heatmapData.valores.get(`${mes}|${estado}`) ?? 0;
                    const intensity = heatmapData.maxVal > 0 ? value / heatmapData.maxVal : 0;
                    const etiqueta = `${estadoLabel(estado)} - ${mes}: ${value}`;
                    return (
                      <Pista key={`${estado}-${mes}`} contenido={etiqueta}>
                        <div
                          className={cn(
                            "w-14 h-8 shrink-0 m-0.5 rounded-sm text-xs font-medium transition-colors",
                            intensity > 0.55 ? "text-primary-foreground" : "text-foreground/80",
                          )}
                          style={heatmapCellStyle(value, heatmapData.maxVal)}
                        >
                          {value > 0 && (
                            <Link
                              href={scopedHref(mesHref(mes, estado))}
                              tabIndex={-1}
                              aria-label={`${etiqueta}. Ver licitaciones`}
                              className="flex h-full w-full items-center justify-center rounded-sm hover:ring-2 hover:ring-ring"
                            >
                              {value}
                            </Link>
                          )}
                        </div>
                      </Pista>
                    );
                  })}
                </div>
              ))}
              <div className="flex items-center gap-2 mt-4">
                <span className="text-xs text-muted-foreground">Menos</span>
                {HEATMAP_LEGEND_STEPS.map((alpha, i) => (
                  <div
                    key={i}
                    className="w-6 h-4 rounded-sm border border-border/40"
                    style={{
                      backgroundColor:
                        alpha === 0
                          ? "hsl(var(--muted) / 0.4)"
                          : `hsl(var(--primary) / ${alpha})`,
                    }}
                  />
                ))}
                <span className="text-xs text-muted-foreground">Mas</span>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}
