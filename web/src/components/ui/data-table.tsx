"use client";

import * as React from "react";
import {
  columnVisibilityFeature,
  createSortedRowModel,
  flexRender,
  rowSortingFeature,
  sortFns,
  tableFeatures,
  useTable,
  type ColumnDef,
  type Row,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn, formatNumber } from "@/lib/utils";
import { useAnnounceOnChange } from "@/components/live-region";

/**
 * Features de v9 que usa esta tabla: ordenación en cliente y nada más.
 *
 * En v8 cada feature venía incluida de serie; v9 obliga a registrarlas y a
 * declarar el row model de cada una en su slot. El objeto se exporta porque
 * los tipos públicos (`ColumnDef`, `Row`, ...) ahora llevan `TFeatures` como
 * primer parámetro: quien define columnas para esta tabla necesita
 * `typeof dataTableFeatures` para que encajen.
 */
export const dataTableFeatures = tableFeatures({
  rowSortingFeature,
  // `row.getVisibleCells()` vive en esta feature: sin registrarla el método no
  // existe (v9 no trae nada de serie) y el fallo sale como error de tipos en
  // el render, no como una tabla vacía.
  columnVisibilityFeature,
  sortedRowModel: createSortedRowModel(),
  // Ninguna columna declara `sortFn`, así que todas resuelven por
  // autodetección; el registro completo garantiza que la clave que elija
  // `getAutoSortFn` (basic/text/datetime/alphanumeric) esté disponible.
  sortFns,
});

export type DataTableFeatures = typeof dataTableFeatures;

/**
 * Flecha de orden de una cabecera de columna. `aria-hidden`: el estado de orden
 * lo anuncia el `aria-sort` del `<th>`, no el icono.
 *
 * La columna activa enseña su sentido (`ArrowUp`/`ArrowDown`) en el color del
 * texto. Las demás no enseñan nada en reposo —«↑↓» detrás de las once
 * cabeceras a la vez era ruido— y la doble flecha aparece al pasar el ratón o
 * al enfocar la cabecera (la cabecera lleva `group`). En táctil, sin hover, se
 * queda visible y tenue: si no, nada diría que la columna se puede ordenar.
 */
export function IndicadorOrden({
  direccion,
  className,
}: {
  direccion: "asc" | "desc" | false | null | undefined;
  className?: string;
}) {
  if (direccion === "asc") {
    return <ArrowUp className={cn("h-3 w-3 flex-none text-foreground", className)} aria-hidden="true" />;
  }
  if (direccion === "desc") {
    return <ArrowDown className={cn("h-3 w-3 flex-none text-foreground", className)} aria-hidden="true" />;
  }
  return (
    <ArrowUpDown
      className={cn(
        "h-3 w-3 flex-none opacity-0 transition-opacity group-hover:opacity-60 group-focus-visible:opacity-60 pointer-coarse:opacity-40",
        className,
      )}
      aria-hidden="true"
    />
  );
}

/** `ColumnDef` ya ligado a las features de esta tabla. */
export type DataTableColumnDef<TData extends RowData, TValue = unknown> =
  ColumnDef<DataTableFeatures, TData, TValue>;

interface DataTableProps<TData extends RowData, TValue> {
  columns: DataTableColumnDef<TData, TValue>[];
  data: TData[];
  initialSorting?: SortingState;
  emptyMessage?: string;
  getRowClassName?: (row: Row<DataTableFeatures, TData>) => string | undefined;
  className?: string;
  /**
   * Cómo nombrar las filas al anunciar el recuento ("licitaciones", "empresas").
   * Con `null` la tabla no anuncia: útil cuando la página ya anuncia su propio
   * recuento y dos mensajes se pisarían.
   */
  rowNoun?: string | null;
}

export function DataTable<TData extends RowData, TValue>({
  columns,
  data,
  initialSorting = [],
  emptyMessage = "Sin datos disponibles",
  getRowClassName,
  className,
  rowNoun = "resultados",
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = React.useState<SortingState>(initialSorting);

  // El salto de 4.000 filas a 12 tras filtrar era invisible sin lector: la tabla
  // se redibujaba en silencio. Sólo se anuncia el cambio, no el montaje.
  useAnnounceOnChange(
    rowNoun === null
      ? null
      : data.length === 0
        ? emptyMessage
        : `${formatNumber(data.length)} ${rowNoun}`,
  );

  const table = useTable({
    features: dataTableFeatures,
    data,
    // `useTable` tipa la lista como `ColumnDef<..., TData, unknown>[]` y
    // `ColumnDef` es invariante en `TValue`, así que un array con un `TValue`
    // concreto no es asignable aunque en runtime sea el mismo objeto. En v8
    // colaba por varianza. Se conserva `TValue` en la prop pública —es lo que
    // le da tipo al `getValue()` de cada celda— y se ensancha sólo aquí.
    columns: columns as DataTableColumnDef<TData>[],
    state: { sorting },
    onSortingChange: setSorting,
  });

  return (
    <div className={cn(className)}>
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const canSort = header.column.getCanSort();
                const sorted = header.column.getIsSorted();
                return (
                  <TableHead
                    key={header.id}
                    aria-sort={
                      sorted === "asc"
                        ? "ascending"
                        : sorted === "desc"
                          ? "descending"
                          : canSort
                            ? "none"
                            : undefined
                    }
                    className={cn(
                      canSort &&
                        "group cursor-pointer select-none transition-colors hover:text-foreground",
                    )}
                    onClick={header.column.getToggleSortingHandler()}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        header.column.getToggleSortingHandler()?.(e);
                      }
                    }}
                    tabIndex={canSort ? 0 : undefined}
                  >
                    {header.isPlaceholder ? null : (
                      <span className="inline-flex items-center gap-1">
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                        {canSort && <IndicadorOrden direccion={sorted} />}
                      </span>
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length > 0 ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id} className={getRowClassName?.(row)}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="py-8 text-center text-tf-meta text-muted-foreground"
              >
                {emptyMessage}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
