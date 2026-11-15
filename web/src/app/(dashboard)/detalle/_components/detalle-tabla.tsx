"use client";

import type { SortingState } from "@tanstack/react-table";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { IndicadorOrden } from "@/components/ui/indicador-orden";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { MergedRow } from "../_hooks/detalle-table-model";
import { COLUMNAS_DE_DATO, COLUMNS, TABLE_MIN_WIDTH } from "./detalle-columnas";
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
      <tr className="h-[30px] border-b border-divider">
        <th scope="col" className="px-1 pl-3.5">
          <Checkbox
            className="relative h-3.5 w-3.5 after:absolute after:-inset-1.5 after:content-['']"
            aria-label="Seleccionar todas las filas de la página"
            checked={allPageSelected}
            onCheckedChange={onToggleAllPage}
          />
        </th>
        <th scope="col" aria-label="Novedad y favorito" />
        {COLUMNAS_DE_DATO.map((column, indice) => {
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
                indice === COLUMNAS_DE_DATO.length - 1 && "pr-3.5",
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

/**
 * Lo que pinta el cuerpo de la tabla: uno de cuatro, nunca dos a la vez.
 *
 * - `vacia.conRecorte`: el texto y el botón cambian si además hay recorte por
 *   cierre.
 * - `filas.refrescando`: hay otra página o filtro en vuelo; las filas que se
 *   ven son las anteriores y se atenúan.
 */
export type EstadoTabla =
  | { tipo: "cargando" }
  | { tipo: "error"; error: unknown }
  | { tipo: "vacia"; conRecorte: boolean }
  | { tipo: "filas"; refrescando: boolean };

export function estadoDeTabla({
  isLoading,
  isFetching,
  error,
  hayFilas,
  conRecorte,
}: {
  isLoading: boolean;
  isFetching: boolean;
  error: unknown;
  hayFilas: boolean;
  conRecorte: boolean;
}): EstadoTabla {
  if (isLoading) return { tipo: "cargando" };
  if (error != null) return { tipo: "error", error };
  if (!hayFilas) return { tipo: "vacia", conRecorte };
  return { tipo: "filas", refrescando: isFetching };
}

export interface DetalleTablaProps {
  rows: MergedRow[];
  sorting: SortingState;
  allPageSelected: boolean;
  onToggleAllPage: () => void;
  onToggleSort: (columnId: string) => void;
  estado: EstadoTabla;
  onRetry: () => void;
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
  const { rows, estado } = props;

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
            {estado.tipo === "cargando" &&
              Array.from({ length: 12 }, (_, index) => (
                <tr key={index} className="border-b border-divider-subtle">
                  <td colSpan={COLUMNS.length} className="px-3.5 py-1.5">
                    <Skeleton className="h-6 w-full rounded-sm" />
                  </td>
                </tr>
              ))}
            {estado.tipo === "filas" &&
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
                  atenuada={estado.refrescando}
                  onOpen={props.onOpen}
                  onToggleSelect={props.onToggleSelect}
                  onToggleCcaa={props.onToggleCcaa}
                  onToggleTecnologia={props.onToggleTecnologia}
                />
              ))}
          </tbody>
        </table>

        {/* Los tres estados viven fuera de la `<table>`: una alerta dentro
            de una celda se anuncia como dato de la tabla, que es lo que no
            es. La cabecera de columnas se queda visible en los tres. */}
        {estado.tipo === "error" && (
          <PanelError
            title="No se pudo cargar la tabla"
            error={estado.error}
            onRetry={props.onRetry}
            className="mx-auto my-10 max-w-[560px]"
          />
        )}

        {estado.tipo === "vacia" && (
          <PanelEmpty
            className="py-20"
            title="Sin resultados"
            hint={
              estado.conRecorte
                ? "Ninguna licitación encaja con el ámbito actual ni con el recorte por fecha de cierre."
                : "Ninguna licitación encaja con el ámbito actual."
            }
            action={
              <Button type="button" variant="outline" size="sm" onClick={props.onLimpiar}>
                {estado.conRecorte ? "Limpiar ámbito y recorte" : "Limpiar ámbito"}
              </Button>
            }
          />
        )}
      </div>
    </div>
  );
}
