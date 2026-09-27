"use client";

import * as React from "react";
import { FiltroEtiquetaSelect } from "@/components/etiquetas/filtro-etiqueta";
import { ROTULO_DATO, Segmented } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  SEGMENTS,
  SORTS,
  type SegmentKey,
  type SortKey,
} from "../_hooks/use-radar-consola";

/**
 * Bandejas y orden. Una línea cuando cabe y dos cuando no: el grupo derecho
 * (restaurar, etiquetas y orden) salta **entero** debajo de las bandejas,
 * alineado a la derecha, en vez de pintarse encima del inspector.
 *
 * Con el inspector visible (xl) la columna mide 781 px a 1280 y 941 a 1440; las
 * bandejas ocupan unos 520 y el grupo derecho hasta unos 520 con «Restaurar» y
 * el filtro de etiquetas. Con `lg:flex-nowrap` el grupo se salía de la columna
 * y caía sobre el inspector, y `e2e/responsive.spec.ts` no lo veía porque
 * `main` no llegaba a desbordar: medía el desbordamiento en la caja equivocada.
 * `data-slot="radar-controles"` es el ancla para el E2E que lo vigile.
 *
 * Bandejas y orden son conmutadores (`Segmented`, con `aria-pressed`), no
 * pestañas: no hay un panel por opción, cambia la lista que ya está debajo.
 *
 * El orden **sólo aplica a las bandejas puntuadas**. «Próximas» (T5) no tiene
 * score ni plazo —son expedientes sin pliego— y la ordena el servidor por
 * fecha prevista: dejar los tres botones activos ahí ofrecería un criterio que
 * no cambiaría nada, que es peor que no ofrecerlo.
 */
export function RadarControles({
  segment,
  onSegment,
  counts,
  sort,
  onSort,
  dismissedCount,
  onRestoreAll,
  etiqueta,
  onEtiqueta,
}: {
  segment: SegmentKey;
  onSegment: (segment: SegmentKey) => void;
  /** `null` = todavía no se sabe; se pinta «—» y no un cero que afirma. */
  counts: Record<SegmentKey, number | null>;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  dismissedCount: number;
  onRestoreAll: () => void;
  /** F1.6 — filtro por etiqueta; sin etiquetas en la organización no se pinta. */
  etiqueta?: string;
  onEtiqueta?: (etiqueta: string) => void;
}) {
  const conOrden = segment !== "proximas";
  const bandejas = React.useMemo(
    () => SEGMENTS.map((item) => ({ value: item.key, label: item.label, count: counts[item.key] ?? "—" })),
    [counts],
  );
  const ordenes = React.useMemo(() => SORTS.map((item) => ({ value: item.key, label: item.label })), []);

  return (
    <div
      data-slot="radar-controles"
      className="flex min-h-11 flex-none flex-wrap items-center gap-x-1 gap-y-1.5 border-b border-border/60 px-3 py-2 md:px-3.5"
    >
      {/* 32 px de alto en móvil (la talla `sm` de Segmented): es un control
          que se pulsa con el pulgar, y 28 px queda justo por encima del mínimo
          de WCAG 2.5.8 pero se falla igual. */}
      <Segmented aria-label="Bandejas" value={segment} onChange={onSegment} options={bandejas} />

      {/* En móvil ocupa su propia línea, alineada a la izquierda; desde `md` va
          a la derecha y, si no cabe junto a las bandejas, baja entero. */}
      <div className="flex basis-full flex-wrap items-center gap-x-1.5 gap-y-1.5 md:ml-auto md:basis-auto md:justify-end">
        {dismissedCount > 0 && (
          <Button type="button" variant="outline" size="sm" onClick={onRestoreAll} className="flex-none">
            Restaurar {dismissedCount} descartada{dismissedCount === 1 ? "" : "s"}
          </Button>
        )}
        {conOrden && etiqueta != null && onEtiqueta && (
          // Filtra las señales que ya están en pantalla: el ranking no admite etiqueta.
          <FiltroEtiquetaSelect
            value={etiqueta}
            onChange={onEtiqueta}
            alcance="en las señales cargadas"
            className="h-8 w-40 flex-none md:h-7"
          />
        )}
        {conOrden ? (
          <div className="flex flex-none items-center gap-1.5">
            <span className={cn(ROTULO_DATO, "flex-none")} aria-hidden="true">
              Orden
            </span>
            <Segmented aria-label="Orden" value={sort} onChange={onSort} options={ordenes} />
          </div>
        ) : (
          <span className={cn(ROTULO_DATO, "flex-none")}>Orden: fecha prevista</span>
        )}
      </div>
    </div>
  );
}
