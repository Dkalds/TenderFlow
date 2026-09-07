"use client";

/**
 * Las dos tablas de Geografía: el listado de CCAAs —que además filtra— y el de
 * provincias. Ambas ordenan por la misma cabecera clicable, así que el botón
 * con las tres flechas (activa ascendente, activa descendente, inactiva) vive
 * una sola vez aquí.
 */

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type {
  GeoItem,
  ProvSortKey,
  ProvinciaItem,
  SortDir,
  SortKey,
} from "../_hooks/use-geografia-view";

/** Cabecera ordenable: rotula la columna y anuncia por cuál se está ordenando. */
function SortableHead<K extends string>({
  columnKey,
  label,
  numeric,
  activeKey,
  dir,
  onSort,
}: {
  columnKey: K;
  label: string;
  /** Las columnas de cifras se alinean a la derecha; la de texto, no. */
  numeric: boolean;
  activeKey: K;
  dir: SortDir;
  onSort: (key: K) => void;
}) {
  return (
    <TableHead
      className={`pb-2 pr-4 font-medium text-muted-foreground ${numeric ? "text-right" : ""}`}
    >
      <Button
        variant="ghost"
        size="sm"
        className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
        onClick={() => onSort(columnKey)}
      >
        {label}
        {activeKey === columnKey ? (
          dir === "asc" ? (
            <ArrowUp className="ml-1 h-3 w-3 text-primary" />
          ) : (
            <ArrowDown className="ml-1 h-3 w-3 text-primary" />
          )
        ) : (
          <ArrowUpDown className="ml-1 h-3 w-3 opacity-40" />
        )}
      </Button>
    </TableHead>
  );
}

function TablaSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

const COLUMNAS_CCAA: [SortKey, string][] = [
  ["ccaa", "CCAA"],
  ["count", "Cantidad"],
  ["importe", "Importe"],
  ["pct", "%"],
];

export function GeografiaTablaCcaa({
  filas,
  sortKey,
  sortDir,
  onSort,
  activeCcaa,
  onToggleCcaa,
  isLoading,
}: {
  filas: GeoItem[];
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  /** CCAAs marcadas en el ámbito global: se resaltan como filtro activo. */
  activeCcaa: Set<string>;
  onToggleCcaa: (ccaa: string) => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Todas las CCAAs</CardTitle>
        <CardDescription>Clic en una CCAA para filtrar</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <TablaSkeleton />
        ) : (
          <div className="overflow-x-auto">
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="border-b text-left">
                  {COLUMNAS_CCAA.map(([key, label]) => (
                    <SortableHead
                      key={key}
                      columnKey={key}
                      label={label}
                      numeric={key !== "ccaa"}
                      activeKey={sortKey}
                      dir={sortDir}
                      onSort={onSort}
                    />
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((item, idx) => {
                  const isActive = activeCcaa.has(item.ccaa);
                  return (
                  <TableRow
                    key={idx}
                    onClick={() => onToggleCcaa(item.ccaa)}
                    className={`cursor-pointer border-b border-border/50 hover:bg-muted/50 ${isActive ? "bg-primary/10" : ""}`}
                  >
                    {/* El conmutador es un botón real dentro de la celda, no
                        la fila. `aria-pressed` sobre un `<tr>` no lo lee
                        nadie —`row` no admite ese estado— y la fila entera no
                        era alcanzable por teclado: quien no usa ratón no
                        tenía forma de filtrar por CCAA desde esta tabla.
                        El `onClick` del `<tr>` sobrevive como atajo. */}
                    <TableCell className="py-2 pr-4 font-medium">
                      <button
                        type="button"
                        aria-pressed={isActive}
                        className="cursor-pointer text-left font-medium"
                        onClick={(e) => {
                          // Si no se corta, el clic sube al `<tr>` y el toggle
                          // se aplica dos veces (vuelve al estado inicial).
                          e.stopPropagation();
                          onToggleCcaa(item.ccaa);
                        }}
                      >
                        {item.ccaa}
                      </button>
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">
                      {formatNumber(item.count)}
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">
                      {formatCurrency(item.importe)}
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">
                      {formatPercent(item.pct)}
                    </TableCell>
                  </TableRow>
                  );
                })}
                {filas.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="py-8 text-center text-muted-foreground"
                    >
                      Sin resultados
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const COLUMNAS_PROVINCIA: [ProvSortKey, string][] = [
  ["provincia", "Provincia"],
  ["count", "Cantidad"],
  ["importe", "Importe"],
];

export function GeografiaTablaProvincias({
  filas,
  sortKey,
  sortDir,
  onSort,
  isLoading,
}: {
  filas: ProvinciaItem[];
  sortKey: ProvSortKey;
  sortDir: SortDir;
  onSort: (key: ProvSortKey) => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Provincias</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <TablaSkeleton />
        ) : filas.length > 0 ? (
          <div className="overflow-x-auto">
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="border-b text-left">
                  {COLUMNAS_PROVINCIA.map(([key, label]) => (
                    <SortableHead
                      key={key}
                      columnKey={key}
                      label={label}
                      numeric={key !== "provincia"}
                      activeKey={sortKey}
                      dir={sortDir}
                      onSort={onSort}
                    />
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((item, idx) => (
                  <TableRow
                    key={idx}
                    className="border-b border-border/50 hover:bg-muted/50"
                  >
                    <TableCell className="py-2 pr-4 font-medium">
                      {item.provincia}
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">
                      {formatNumber(item.count)}
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">
                      {formatCurrency(item.importe)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="py-8 text-center text-muted-foreground">
            Sin datos de provincia
          </p>
        )}
      </CardContent>
    </Card>
  );
}
