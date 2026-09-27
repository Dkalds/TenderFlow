"use client";

import * as React from "react";
import Link from "next/link";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { RadarTender } from "@/hooks/use-radar";
import { RadarEsqueleto } from "./radar-esqueleto";
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
      className={cn("hidden h-[30px] flex-none items-center border-b border-border/70 bg-card md:grid", CABECERA_COLUMNA, RADAR_GRID)}
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

/** Lista de señales con sus tres estados: fallo, carga y bandeja al día. */
export function RadarLista({
  listRef,
  rows,
  activeIndex,
  lastVisit,
  rowHeight,
  enTabla,
  conFicha,
  isLoading,
  error,
  onRetry,
  onSelect,
  onDismiss,
  onFollowed,
  onOpenPursuit,
  onOpenFicha,
  onExplicacion,
  afinidadOrigen,
}: {
  listRef: React.RefObject<HTMLDivElement | null>;
  rows: RadarTender[];
  activeIndex: number;
  lastVisit: number;
  rowHeight: number;
  enTabla: boolean;
  conFicha: boolean;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  onSelect: (index: number) => void;
  onDismiss: (tender: RadarTender) => void;
  onFollowed: (tender: RadarTender, ahoraSigue: boolean) => void;
  onOpenPursuit: (tender: RadarTender) => void;
  onOpenFicha: (index: number) => void;
  onExplicacion?: (tender: RadarTender) => void;
  /** Origen del portfolio de afinidad (S2.4). Viaja de la respuesta a cada
   *  desglose: es de la petición, no de la fila. */
  afinidadOrigen?: string | null;
}) {
  const showEmpty = !isLoading && !error && rows.length === 0;

  return (
    <div data-slot="radar-lista" ref={listRef} className="relative min-h-0 flex-1 overflow-y-auto">
      {error ? (
        // `useRadar` no es de esta pantalla: el `meta` que calla el toast lo
        // tiene que poner el hook (ver el handoff de la fase 2).
        <PanelError
          title="No se pudo cargar la bandeja del Radar"
          error={error}
          onRetry={onRetry}
          className="mx-auto my-10 max-w-[560px]"
        />
      ) : isLoading ? (
        <RadarEsqueleto barras={9} />
      ) : showEmpty ? (
        // Un vacío que dice qué hacer (C7.3). Las dos salidas existen: el Radar
        // aplica la tecnología del ámbito, y las reglas de Mi Watchlist avisan
        // desde el servidor según su frecuencia.
        <PanelEmpty
          className="py-16"
          title="Bandeja al día"
          hint={
            <>
              No quedan señales con el ámbito actual. Si has acotado la tecnología en la barra de
              ámbito, quítala para ver el resto. Para enterarte de lo que se publique sin volver
              aquí, crea una regla en{" "}
              <Link href="/mi-watchlist" className="font-medium text-primary hover:underline">
                Mi Watchlist
              </Link>
              .
            </>
          }
        />
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
              isNew={lastVisit > 0 && publicado > lastVisit}
              rowHeight={rowHeight}
              enTabla={enTabla}
              conFicha={conFicha}
              onSelect={onSelect}
              onDismiss={onDismiss}
              onFollowed={onFollowed}
              onOpenPursuit={onOpenPursuit}
              onOpenFicha={onOpenFicha}
              onExplicacion={onExplicacion}
              afinidadOrigen={afinidadOrigen}
            />
          );
        })
      )}
    </div>
  );
}
