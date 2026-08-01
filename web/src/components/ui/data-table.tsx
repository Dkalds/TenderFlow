"use client";

import * as React from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
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

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  initialSorting?: SortingState;
  emptyMessage?: string;
  getRowClassName?: (row: Row<TData>) => string | undefined;
  className?: string;
  /**
   * Cómo nombrar las filas al anunciar el recuento ("licitaciones", "empresas").
   * Con `null` la tabla no anuncia: útil cuando la página ya anuncia su propio
   * recuento y dos mensajes se pisarían.
   */
  rowNoun?: string | null;
}

export function DataTable<TData, TValue>({
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

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
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
                        "cursor-pointer select-none hover:text-foreground transition-colors",
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
                        {canSort &&
                          (sorted === "asc" ? (
                            <ArrowUp className="h-3.5 w-3.5 shrink-0 text-primary" />
                          ) : sorted === "desc" ? (
                            <ArrowDown className="h-3.5 w-3.5 shrink-0 text-primary" />
                          ) : (
                            <ArrowUpDown className="h-3.5 w-3.5 shrink-0 opacity-40" />
                          ))}
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
                className="py-8 text-center text-muted-foreground"
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
