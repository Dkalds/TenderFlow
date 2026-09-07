"use client";

/**
 * El multiselector de CPVs de Tendencias CPV.
 *
 * El color del punto y del borde sale del índice del CPV en la lista completa,
 * no de su posición entre los seleccionados: así un CPV conserva su color al
 * marcarlo y desmarcarlo, y coincide con el de su línea en el gráfico.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { getSeriesColor } from "@/lib/chart-colors";

import type { CpvSeries } from "../_hooks/use-tendencias-cpv-view";

export function TendenciasCpvSelector({
  allCpvs,
  effectiveCpvs,
  onToggle,
  isLoading,
}: {
  allCpvs: CpvSeries[];
  /** Códigos CPV que se están pintando (la selección real o el arranque top-3). */
  effectiveCpvs: Set<string>;
  onToggle: (cpv: string) => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Seleccionar CPVs</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto">
            {allCpvs.map((cpvItem, idx) => {
              const isSelected = effectiveCpvs.has(cpvItem.cpv);
              return (
                <label
                  key={cpvItem.cpv}
                  className="inline-flex items-center gap-1.5 cursor-pointer rounded-md border px-2.5 py-1.5 text-sm transition-colors hover:bg-muted"
                  style={isSelected ? { borderColor: getSeriesColor(idx) } : undefined}
                >
                  <Checkbox
                    className="h-5 w-5"
                    checked={isSelected}
                    onCheckedChange={() => onToggle(cpvItem.cpv)}
                  />
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: getSeriesColor(idx) }}
                  />
                  <span>{cpvItem.label || cpvItem.cpv}</span>
                </label>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
