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
export function RadarCabecera() {
  return (
    <div
      data-slot="radar-cabecera"
      className={cn(
        "hidden h-[30px] flex-none items-center border-b border-border/70 bg-card/50 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground md:grid",
        RADAR_GRID,
      )}
    >
      <span>Score</span>
      <span>Licitación</span>
      <span>Órgano</span>
      <span>Tecnología</span>
      <span className="text-right">Importe</span>
      <span className="text-right">Plazo</span>
      <span className="text-right">Acción</span>
    </div>
  );
}

function RadarError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mx-auto my-10 max-w-[560px] rounded-xl border border-destructive/40 bg-destructive/8 px-6 py-5"
    >
      <div className="mb-2 flex items-center gap-2.5">
        <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-destructive/50 text-[12px] font-semibold text-destructive">
          !
        </span>
        <span className="text-[13.5px] font-semibold text-destructive">
          Error al cargar la bandeja del radar
        </span>
      </div>
      <p className="mb-3.5 font-mono text-xs leading-[1.55] text-destructive/80">{error.message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="tf-pressable h-[30px] rounded-md border border-border/80 px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
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
  afinidadOrigen,
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
  /** Origen del portfolio de afinidad (S2.4). Viaja de la respuesta a cada
   *  desglose: es de la petición, no de la fila. */
  afinidadOrigen?: string | null;
}) {
  const showEmpty = !isLoading && !error && rows.length === 0;

  return (
    <div data-slot="radar-lista" ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
      {error ? (
        <RadarError error={error as Error} onRetry={onRetry} />
      ) : isLoading ? (
        <div className="flex flex-col gap-2.5 p-3.5">
          {Array.from({ length: 9 }, (_, index) => (
            <span
              key={index}
              className="tf-shimmer block h-11 rounded-lg"
              style={{ opacity: 1 - index * 0.07 }}
            />
          ))}
        </div>
      ) : showEmpty ? (
        <div className="px-5 py-20 text-center">
          <RadioTower className="mx-auto mb-3 h-6 w-6 text-muted-foreground/60" aria-hidden="true" />
          <div className="mb-1.5 font-display text-[15px] font-semibold leading-[1.3]">
            Bandeja al día
          </div>
          <p className="text-[13px] leading-[1.5] text-muted-foreground">
            No quedan señales con el ámbito actual.
          </p>
        </div>
      ) : (
        rows.map((tender, index) => {
          const publicado = tender.fecha_publicacion
            ? new Date(tender.fecha_publicacion).getTime()
            : 0;
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
              afinidadOrigen={afinidadOrigen}
            />
          );
        })
      )}
    </div>
  );
}
