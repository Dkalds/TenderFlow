"use client";

import * as React from "react";
import { RadioTower } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RadarTender } from "@/hooks/use-radar";
import { RadarFila } from "./radar-fila";
import { RADAR_GRID } from "./radar-shared";

/**
 * Cabecera de columnas. Decisión escrita: por debajo de `md` no se renderiza
 * porque no hay columnas que rotular — en la ficha cada dato lleva su propia
 * forma (color de banda, «d» del plazo, «€» del importe) y un rótulo por celda
 * sería ruido, no ayuda.
 */
export function RadarCabecera({ enRejilla = false }: { enRejilla?: boolean }) {
  return (
    <div
      data-slot="radar-cabecera"
      // La cabecera es la primera fila de la rejilla, pero sólo cuando hay
      // rejilla: sin filas no hay `grid` que encabezar, y un `row` suelto es un
      // rol que miente sobre su contexto.
      role={enRejilla ? "row" : undefined}
      aria-rowindex={enRejilla ? 1 : undefined}
      className={cn(
        "border-border/70 bg-card/50 text-muted-foreground hidden h-[30px] flex-none items-center border-b font-mono text-[9px] font-semibold tracking-[0.1em] uppercase md:grid",
        RADAR_GRID,
      )}
    >
      <span role={enRejilla ? "columnheader" : undefined}>Score</span>
      <span role={enRejilla ? "columnheader" : undefined}>Licitación</span>
      <span role={enRejilla ? "columnheader" : undefined}>Órgano</span>
      <span role={enRejilla ? "columnheader" : undefined}>Tecnología</span>
      <span role={enRejilla ? "columnheader" : undefined} className="text-right">
        Importe
      </span>
      <span role={enRejilla ? "columnheader" : undefined} className="text-right">
        Plazo
      </span>
      <span role={enRejilla ? "columnheader" : undefined} className="text-right">
        Acción
      </span>
    </div>
  );
}

function RadarError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="border-destructive/40 bg-destructive/8 mx-auto my-10 max-w-[560px] rounded-xl border px-6 py-5"
    >
      <div className="mb-2 flex items-center gap-2.5">
        <span className="border-destructive/50 text-destructive grid h-5.5 w-5.5 flex-none place-items-center rounded-full border text-[12px] font-semibold">
          !
        </span>
        <span className="text-destructive text-[13.5px] font-semibold">Error al cargar la bandeja del radar</span>
      </div>
      <p className="text-destructive/80 mb-3.5 font-mono text-xs leading-[1.55]">{error.message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="tf-pressable border-border/80 text-muted-foreground hover:text-foreground h-[30px] rounded-md border px-3 text-xs font-medium transition-colors"
      >
        ↻ Reintentar
      </button>
    </div>
  );
}

/** Lista de señales con sus tres estados: fallo, carga y bandeja al día. */
export function RadarLista({
  listRef,
  rows,
  activeIndex,
  followedIds,
  lastVisit,
  rowHeight,
  enTabla,
  conFicha,
  isLoading,
  error,
  onRetry,
  onSelect,
  onDismiss,
  onFollow,
  onOpenPursuit,
  onOpenFicha,
}: {
  listRef: React.RefObject<HTMLDivElement | null>;
  rows: RadarTender[];
  activeIndex: number;
  followedIds: Set<string>;
  lastVisit: number;
  rowHeight: number;
  enTabla: boolean;
  conFicha: boolean;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  onSelect: (index: number) => void;
  onDismiss: (tender: RadarTender) => void;
  onFollow: (tender: RadarTender) => void;
  onOpenPursuit: (tender: RadarTender) => void;
  onOpenFicha: (index: number) => void;
}) {
  const showEmpty = !isLoading && !error && rows.length === 0;
  // La rejilla existe sólo cuando hay filas. Un `grid` cuyo contenido son nueve
  // esqueletos de carga promete una estructura que todavía no está, y axe lo
  // marca con razón (`aria-required-children`): sus hijos tienen que ser filas.
  const hayFilas = rows.length > 0;

  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      role={hayFilas ? "grid" : undefined}
      aria-label={hayFilas ? "Señales del Radar" : undefined}
      // +1 por la cabecera, que es la fila 1.
      aria-rowcount={hayFilas ? rows.length + 1 : undefined}
    >
      <RadarCabecera enRejilla={hayFilas} />
      <div
        data-slot="radar-lista"
        ref={listRef}
        role={hayFilas ? "rowgroup" : undefined}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {error ? (
          <RadarError error={error as Error} onRetry={onRetry} />
        ) : isLoading ? (
          <div className="flex flex-col gap-2.5 p-3.5">
            {Array.from({ length: 9 }, (_, index) => (
              <span key={index} className="tf-shimmer block h-11 rounded-lg" style={{ opacity: 1 - index * 0.07 }} />
            ))}
          </div>
        ) : showEmpty ? (
          <div className="px-5 py-20 text-center">
            <RadioTower className="text-muted-foreground/60 mx-auto mb-3 h-6 w-6" aria-hidden="true" />
            <div className="font-display mb-1.5 text-[15px] leading-[1.3] font-semibold">Bandeja al día</div>
            <p className="text-muted-foreground text-[13px] leading-[1.5]">No quedan señales con el ámbito actual.</p>
          </div>
        ) : (
          rows.map((tender, index) => {
            const publicado = tender.fecha_publicacion ? new Date(tender.fecha_publicacion).getTime() : 0;
            return (
              <RadarFila
                key={tender.id_externo}
                tender={tender}
                index={index}
                isActive={index === activeIndex}
                isFollowed={followedIds.has(tender.id_externo)}
                isNew={lastVisit > 0 && publicado > lastVisit}
                rowHeight={rowHeight}
                enTabla={enTabla}
                conFicha={conFicha}
                onSelect={onSelect}
                onDismiss={onDismiss}
                onFollow={onFollow}
                onOpenPursuit={onOpenPursuit}
                onOpenFicha={onOpenFicha}
              />
            );
          })
        )}
      </div>
    </div>
  );
}
