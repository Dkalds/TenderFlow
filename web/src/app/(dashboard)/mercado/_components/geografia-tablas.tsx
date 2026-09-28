"use client";

/**
 * Las dos tablas de Geografía: el listado de CCAA —que además filtra— y el de
 * provincias. Ambas ordenan por la misma cabecera pulsable, así que el botón
 * de orden vive una sola vez aquí.
 */

import Link from "next/link";

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { IndicadorOrden } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CABECERA_COLUMNA,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useScopedHref } from "@/lib/filters";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type {
  GeoItem,
  ProvSortKey,
  ProvinciaItem,
  SortDir,
  SortKey,
} from "../_hooks/use-geografia-view";

/**
 * Cabecera ordenable: rotula la columna y anuncia por cuál se ordena. El
 * `aria-sort` va en el `<th>` y la versal en el botón (el navegador no se la
 * hereda a un `<button>`).
 */
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
  const activa = activeKey === columnKey;
  return (
    <TableHead
      aria-sort={activa ? (dir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(numeric && "text-right")}
    >
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        className={cn(
          CABECERA_COLUMNA,
          "group inline-flex items-center gap-1 transition-colors hover:text-foreground",
          activa && "text-foreground",
        )}
      >
        {label}
        <IndicadorOrden direccion={activa ? dir : null} />
      </button>
    </TableHead>
  );
}

function TablaSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

const COLUMNAS_CCAA: [SortKey, string][] = [
  ["ccaa", "CCAA"],
  ["count", "Licitaciones"],
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
  /** CCAA marcadas en el ámbito global: se resaltan como filtro activo. */
  activeCcaa: Set<string>;
  onToggleCcaa: (ccaa: string) => void;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title="Todas las CCAA" hint="Pulsa una para filtrar el ámbito" />
      {isLoading ? (
        <TablaSkeleton />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
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
                  className={cn("cursor-pointer", isActive && "bg-primary/10 hover:bg-primary/10")}
                >
                  {/* El conmutador es un botón real dentro de la celda, no
                      la fila. `aria-pressed` sobre un `<tr>` no lo lee
                      nadie —`row` no admite ese estado— y la fila entera no
                      era alcanzable por teclado: quien no usa ratón no
                      tenía forma de filtrar por CCAA desde esta tabla.
                      El `onClick` del `<tr>` sobrevive como atajo. */}
                  <TableCell className="font-medium">
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
                  <TableCell numeric>{formatNumber(item.count)}</TableCell>
                  <TableCell numeric>{formatCurrency(item.importe)}</TableCell>
                  <TableCell numeric>{formatPercent(item.pct)}</TableCell>
                </TableRow>
              );
            })}
            {filas.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                  Ninguna CCAA con licitaciones en el ámbito actual.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}

const COLUMNAS_PROVINCIA: [ProvSortKey, string][] = [
  ["provincia", "Provincia"],
  ["count", "Licitaciones"],
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
  const conAmbito = useScopedHref();
  return (
    <Panel>
      <PanelTitle title="Provincias" hint="Pulsa una para ver sus licitaciones en Detalle" />
      {isLoading ? (
        <TablaSkeleton />
      ) : filas.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
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
              <TableRow key={idx}>
                <TableCell className="font-medium">
                  {/* F1.1 — la provincia sólo la filtra el listado: el
                      enlace abre Detalle con ella y con el resto del
                      ámbito que ya estaba puesto. */}
                  <Link
                    href={conAmbito(`/detalle?provincia=${encodeURIComponent(item.provincia)}`)}
                    aria-label={`Ver en Detalle las licitaciones de ${item.provincia}`}
                    className="inline-flex min-h-6 items-center transition-colors hover:text-primary"
                  >
                    {item.provincia}
                  </Link>
                </TableCell>
                <TableCell numeric>{formatNumber(item.count)}</TableCell>
                <TableCell numeric>{formatCurrency(item.importe)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <PanelEmpty
          title="Sin provincias"
          hint="Las licitaciones del ámbito actual no traen provincia."
        />
      )}
    </Panel>
  );
}
