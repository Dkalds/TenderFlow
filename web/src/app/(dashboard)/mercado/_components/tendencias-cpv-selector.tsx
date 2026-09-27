"use client";

/**
 * El multiselector de CPVs de Tendencias CPV.
 *
 * El color del punto y del borde sale del índice del CPV en la lista completa,
 * no de su posición entre los seleccionados: así un CPV conserva su color al
 * marcarlo y desmarcarlo, y coincide con el de su línea en el gráfico.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
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
    <Panel>
      <PanelTitle title="CPV en el gráfico" hint="Marca los que quieras comparar" />
      <div>
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <div className="relative flex flex-wrap gap-2 max-h-48 overflow-y-auto">
            {allCpvs.map((cpvItem, idx) => {
              const isSelected = effectiveCpvs.has(cpvItem.cpv);
              return (
                <label
                  key={cpvItem.cpv}
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border/60 px-2.5 py-1.5 text-tf-meta transition-colors hover:bg-primary/5"
                  style={isSelected ? { borderColor: getSeriesColor(idx) } : undefined}
                >
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={() => onToggle(cpvItem.cpv)}
                  />
                  <span
                    aria-hidden="true"
                    className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: getSeriesColor(idx) }}
                  />
                  <span>{cpvItem.label || cpvItem.cpv}</span>
                </label>
              );
            })}
          </div>
        )}
      </div>
    </Panel>
  );
}
