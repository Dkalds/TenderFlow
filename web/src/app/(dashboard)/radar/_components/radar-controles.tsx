"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import {
  SEGMENTS,
  SORTS,
  type SegmentKey,
  type SortKey,
} from "../_hooks/use-radar-consola";

/**
 * Segmentos y orden. En móvil envuelve en varias líneas en vez de desbordar:
 * son ocho controles y ninguno se puede esconder sin quitarle al usuario el
 * cambio de bandeja o el criterio de orden.
 */
export function RadarControles({
  segment,
  onSegment,
  counts,
  sort,
  onSort,
  dismissedCount,
  onRestoreAll,
}: {
  segment: SegmentKey;
  onSegment: (segment: SegmentKey) => void;
  counts: Record<SegmentKey, number>;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  dismissedCount: number;
  onRestoreAll: () => void;
}) {
  return (
    <div className="flex min-h-11 flex-none flex-wrap items-center gap-x-0.5 gap-y-1.5 border-b border-border/60 px-3 py-2 md:h-11 md:flex-nowrap md:px-3.5 md:py-0">
      {SEGMENTS.map((item) => {
        const on = segment === item.key;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onSegment(item.key)}
            aria-pressed={on}
            className={cn(
              // 32 px de alto en móvil: es un control que se pulsa con el
              // pulgar, y 28 px queda justo por encima del mínimo de
              // WCAG 2.5.8 pero se falla igual.
              "tf-pressable inline-flex h-8 flex-none items-center gap-[7px] rounded-md border px-2.5 text-[12.5px] font-medium transition-colors duration-150 ease-out md:h-7",
              on
                ? "border-border/70 bg-secondary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
            <span
              className={cn(
                "tf-tnum rounded px-1.5 py-0.5 font-mono text-[10px] font-medium",
                on ? "bg-primary/16 text-primary" : "bg-muted-foreground/12 text-muted-foreground",
              )}
            >
              {counts[item.key]}
            </span>
          </button>
        );
      })}
      {/* En móvil el hueco es un salto de línea: los segmentos ocupan la
          primera y el orden la segunda. A partir de `md` vuelve a ser el
          muelle que empuja el orden al extremo derecho. */}
      <div className="basis-full md:flex-1" />
      {dismissedCount > 0 && (
        <button
          type="button"
          onClick={onRestoreAll}
          className="tf-pressable mr-1.5 h-7 flex-none rounded-md border border-border/70 px-2 text-[11px] font-medium text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground md:h-6"
        >
          Restaurar {dismissedCount} descartada{dismissedCount === 1 ? "" : "s"}
        </button>
      )}
      <span className="mr-1.5 flex-none font-mono text-[8.5px] font-semibold uppercase tracking-[0.11em] text-muted-foreground/70">
        Orden
      </span>
      {SORTS.map((item) => {
        const on = sort === item.key;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onSort(item.key)}
            aria-pressed={on}
            className={cn(
              "tf-pressable h-7 flex-none rounded-md border px-2 text-[11px] font-medium transition-colors duration-150 ease-out md:h-6",
              on
                ? "border-primary/25 bg-primary/10 text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
