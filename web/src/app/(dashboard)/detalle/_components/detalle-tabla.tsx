"use client";

import type { SortingState } from "@tanstack/react-table";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { IndicadorOrden } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { MergedRow } from "../_hooks/detalle-table-model";
import { COLUMNS, TABLE_MIN_WIDTH } from "./detalle-columnas";
import { DetalleFila } from "./detalle-fila";

/**
 * Cabecera con orden asc/desc/none y `aria-sort` por columna. La versal de
 * `CABECERA_COLUMNA` va en el `<button>`: el navegador pone `text-transform:
 * none` a los botones y no la heredan del `<th>`.
 */
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
                "px-1",
                column.align === "right" ? "text-right" : "text-left",
                column.key === "tecnologia" && "pr-3.5",
              )}
            >
              <button
                type="button"
                onClick={() => onToggleSort(column.key)}
                className={cn(
                  CABECERA_COLUMNA,
                  "group inline-flex items-center gap-1 rounded-sm px-1 py-0.5 transition-colors hover:text-foreground",
                  active && "text-foreground",
                )}
              >
                {column.label}
                <IndicadorOrden direccion={active ? (sorting[0].desc ? "desc" : "asc") : null} />
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
  ccaas: string[];
  tecnologias: string[];
  compact: boolean;
  rowHeight: number;
  onOpen: (index: number, id: string) => void;
  onToggleSelect: (id: string) => void;
  onToggleCcaa: (ccaa: string) => void;
  onToggleTecnologia: (tecnologia: string) => void;
}

/** La tabla y sus tres estados: carga, fallo y sin resultados. */
export function DetalleTabla(props: DetalleTablaProps) {
  const { rows, isLoading, error, vacia } = props;

  return (
    <div className="relative min-h-0 flex-1 overflow-auto">
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
                    <Skeleton className="h-6 w-full rounded-sm" />
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
                  ccaaOn={row.ccaa ? props.ccaas.includes(row.ccaa) : false}
                  tecOn={row.tecnologia ? props.tecnologias.includes(row.tecnologia) : false}
                  compact={props.compact}
                  rowHeight={props.rowHeight}
                  atenuada={props.isFetching}
                  onOpen={props.onOpen}
                  onToggleSelect={props.onToggleSelect}
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
          <PanelError
            title="No se pudo cargar la tabla"
            error={error}
            onRetry={props.onRetry}
            className="mx-auto my-10 max-w-[560px]"
          />
        )}

        {vacia && (
          <PanelEmpty
            className="py-20"
            title="Sin resultados"
            hint={
              props.conRecorte
                ? "Ninguna licitación encaja con el ámbito actual ni con el recorte por fecha de cierre."
                : "Ninguna licitación encaja con el ámbito actual."
            }
            action={
              <Button type="button" variant="outline" size="sm" onClick={props.onLimpiar}>
                {props.conRecorte ? "Limpiar ámbito y recorte" : "Limpiar ámbito"}
              </Button>
            }
          />
        )}
      </div>
    </div>
  );
}
