"use client";

/**
 * Heatmap Mes × Estado de Tendencias.
 *
 * La cifra de cada celda es un ESTIMADO declarado, no un cruce real: sale del
 * producto de marginales (distribución global de estados × volumen mensual). El
 * badge y la descripción lo dicen en la propia tarjeta, que es lo que exige
 * ADR-014 para no presentar una síntesis como dato medido.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { estadoLabel } from "@/lib/estados";
import { cn } from "@/lib/utils";

import type { HeatmapEstimado } from "../_hooks/use-tendencias-view";

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
  heatmapData: HeatmapEstimado | null;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">Heatmap: Mes x Estado</CardTitle>
          <Badge variant="outline" className="text-amber-600 border-amber-400">
            Estimado
          </Badge>
        </div>
        <CardDescription>
          Estimación a partir de marginales (distribución global de estados ×
          volumen mensual), no un cruce real Mes×Estado. Pendiente de exponer el
          cross-tab real en backend.
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
                  <div key={mes} className="w-14 shrink-0 text-center text-xs text-muted-foreground truncate px-0.5" title={mes}>
                    {mes.length > 7 ? mes.slice(5) : mes}
                  </div>
                ))}
              </div>
              {heatmapData.estados.map((estado) => (
                <div key={estado} className="flex items-center">
                  {/* `por_estado` viaja con el código de la columna, no con la
                      etiqueta: sin traducir, la fila del heatmap se rotula "AGR". */}
                  <div className="w-32 shrink-0 text-xs text-muted-foreground truncate pr-2" title={estadoLabel(estado)}>{estadoLabel(estado)}</div>
                  {heatmapData.meses.map((mes) => {
                    const cell = heatmapData.grid.find((g) => g.mes === mes && g.estado === estado);
                    const value = cell?.value ?? 0;
                    const intensity = heatmapData.maxVal > 0 ? value / heatmapData.maxVal : 0;
                    return (
                      <div
                        key={`${estado}-${mes}`}
                        className={cn(
                          "w-14 h-8 shrink-0 m-0.5 rounded-sm flex items-center justify-center text-xs font-medium transition-colors",
                          intensity > 0.55 ? "text-primary-foreground" : "text-foreground/80",
                        )}
                        style={heatmapCellStyle(value, heatmapData.maxVal)}
                        title={`${estadoLabel(estado)} - ${mes}: ${value}`}
                      >
                        {value > 0 ? value : ""}
                      </div>
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
