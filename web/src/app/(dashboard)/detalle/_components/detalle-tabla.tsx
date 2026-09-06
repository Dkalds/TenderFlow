"use client";

import type { SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { MergedRow } from "../_hooks/detalle-table-model";
import { COLUMNS, TABLE_MIN_WIDTH } from "./detalle-columnas";
import { DetalleFila } from "./detalle-fila";

/** Cabecera con orden asc/desc/none y `aria-sort` por columna. */
function DetalleCabecera({
  sorting,
  allPageSelected,
  onToggleAllPage,
  onToggleSort,
}: {
  sorting: SortingState;
  allPageSelected: boolean;
  onToggleAllPage: () => void;
  onToggleSort: (columnId: string) => void;
}) {
  return (
    <thead className="sticky top-0 z-10 bg-card">
      <tr className="h-[30px] border-b border-border/70">
        <th scope="col" className="px-1 pl-3.5">
          <Checkbox
            className="h-3.5 w-3.5"
            aria-label="Seleccionar todas las filas de la página"
            checked={allPageSelected}
            onCheckedChange={onToggleAllPage}
          />
        </th>
        <th scope="col" aria-label="Novedad" />
        <th scope="col" aria-label="Favorito" />
        {COLUMNS.slice(3).map((column) => {
          const active = sorting[0]?.id === column.key;
          const direction = active ? (sorting[0].desc ? "descending" : "ascending") : "none";
          return (
            <th
              key={column.key}
              scope="col"
              aria-sort={direction}
              className={cn(
                "px-1 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground",
                column.align === "right" ? "text-right" : "text-left",
                column.key === "tecnologia" && "pr-3.5",
              )}
            >
              <button
                type="button"
                onClick={() => onToggleSort(column.key)}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors duration-140 ease-out hover:text-foreground",
                  active && "text-primary",
                )}
              >
                {column.label}
                {active ? (
                  sorting[0].desc ? (
                    <ArrowDown className="h-3 w-3" aria-hidden="true" />
                  ) : (
                    <ArrowUp className="h-3 w-3" aria-hidden="true" />
                  )
                ) : (
                  <ArrowUpDown className="h-3 w-3 opacity-30" aria-hidden="true" />
                )}
              </button>
            </th>
          );
        })}
      </tr>
    </thead>
  );
}

export interface DetalleTablaProps {
  rows: MergedRow[];
  sorting: SortingState;
  allPageSelected: boolean;
  onToggleAllPage: () => void;
  onToggleSort: (columnId: string) => void;
  isLoading: boolean;
  isFetching: boolean;
  error: unknown;
  onRetry: () => void;
  vacia: boolean;
  /** Bloque vacío/error: el texto cambia si además hay recorte por cierre. */
  conRecorte: boolean;
  onLimpiar: () => void;
  detailId: string | null;
  cursor: number;
  rowSelection: Record<string, boolean>;
  watchedIds: Set<string>;
  ccaas: string[];
  tecnologias: string[];
  compact: boolean;
  rowHeight: number;
  onOpen: (index: number, id: string) => void;
  onToggleSelect: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onToggleCcaa: (ccaa: string) => void;
  onToggleTecnologia: (tecnologia: string) => void;
}

/** La tabla y sus tres estados: carga, fallo y sin resultados. */
export function DetalleTabla(props: DetalleTablaProps) {
  const { rows, isLoading, error, vacia } = props;

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div style={{ minWidth: TABLE_MIN_WIDTH }}>
        <table className="w-full table-fixed border-collapse">
          <colgroup>
            {COLUMNS.map((column) => (
              <col key={column.key} style={{ width: column.width }} />
            ))}
          </colgroup>
          <DetalleCabecera
            sorting={props.sorting}
            allPageSelected={props.allPageSelected}
            onToggleAllPage={props.onToggleAllPage}
            onToggleSort={props.onToggleSort}
          />

          <tbody>
            {isLoading ? (
              Array.from({ length: 12 }, (_, index) => (
                <tr key={index} className="border-b border-border/30">
                  <td colSpan={COLUMNS.length} className="px-3.5 py-1.5">
                    <Skeleton className="h-6 w-full rounded" />
                  </td>
                </tr>
              ))
            ) : error || vacia ? null : (
              rows.map((row, index) => (
                <DetalleFila
                  key={row.id_externo}
                  row={row}
                  index={index}
                  open={props.detailId === row.id_externo}
                  picked={Boolean(props.rowSelection[row.id_externo])}
                  isCursor={index === Math.min(props.cursor, rows.length - 1)}
                  favorite={props.watchedIds.has(row.id_externo)}
                  ccaaOn={row.ccaa ? props.ccaas.includes(row.ccaa) : false}
                  tecOn={row.tecnologia ? props.tecnologias.includes(row.tecnologia) : false}
                  compact={props.compact}
                  rowHeight={props.rowHeight}
                  atenuada={props.isFetching}
                  onOpen={props.onOpen}
                  onToggleSelect={props.onToggleSelect}
                  onToggleFavorite={props.onToggleFavorite}
                  onToggleCcaa={props.onToggleCcaa}
                  onToggleTecnologia={props.onToggleTecnologia}
                />
              ))
            )}
          </tbody>
        </table>

        {/* Los tres estados viven fuera de la `<table>`: una alerta dentro
            de una celda se anuncia como dato de la tabla, que es lo que no
            es. La cabecera de columnas se queda visible en los tres. */}
        {error != null && (
          <div
            role="alert"
            className="mx-auto my-10 max-w-[560px] rounded-xl border border-destructive/40 bg-destructive/8 px-6 py-5"
          >
            <div className="mb-2 flex items-center gap-2.5">
              <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-destructive/50 text-[12px] font-semibold text-destructive">
                !
              </span>
              <span className="text-[13.5px] font-semibold text-destructive">
                Error al cargar la tabla
              </span>
            </div>
            <p className="mb-3.5 font-mono text-xs leading-[1.55] text-destructive/80">
              {(error as Error).message}
            </p>
            <button
              type="button"
              onClick={props.onRetry}
              className="tf-pressable h-[30px] rounded-md border border-border/80 px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              ↻ Reintentar
            </button>
          </div>
        )}

        {vacia && (
          <div className="px-5 py-[90px] text-center">
            <div className="mb-1.5 font-display text-[15px] font-semibold leading-[1.3]">
              Sin resultados
            </div>
            <p className="mb-3.5 text-[13px] leading-[1.5] text-muted-foreground">
              {props.conRecorte
                ? "Ninguna licitación encaja con el ámbito actual ni con el recorte por fecha de cierre."
                : "Ninguna licitación encaja con el ámbito actual."}
            </p>
            <button
              type="button"
              onClick={props.onLimpiar}
              className="tf-pressable h-[30px] rounded-md border border-primary/40 bg-primary/12 px-3 text-xs font-medium text-primary"
            >
              {props.conRecorte ? "Limpiar ámbito y recorte" : "Limpiar ámbito"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
