"use client";

/**
 * La tabla de competidores: cabecera ordenable, filas y pie con el
 * «mostrando N de M».
 *
 * Va antes que los nueve cortes de gráfico porque es la superficie que los
 * gobierna: antes había que bajar 2.400 px de gráficos para llegar a ella.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";

import type { Competitor, SortKey } from "../_hooks/competidores-types";
import { CompetitorRow } from "./competidor-fila";

const TABLE_COLUMNS: { key: SortKey; label: string }[] = [
  { key: "nombre", label: "Nombre" },
  { key: "nif", label: "NIF" },
  { key: "count", label: "Adjudicaciones" },
  { key: "importe", label: "Importe" },
  { key: "cuota", label: "Cuota %" },
  { key: "contratos_por_anio", label: "Contratos/Año" },
  { key: "importe_medio", label: "Importe Medio" },
  { key: "baja_media", label: "Baja Media %" },
  { key: "ofertas_medias", label: "Ofertas Medias" },
  { key: "pct_monopolio", label: "% Sin comp." },
  { key: "pct_top_organo", label: "% Top Órgano" },
  { key: "ultima", label: "Última Adj." },
];

/**
 * Clave estable de fila: las identidades del maestro primero, luego los NIFs y
 * sólo como último recurso el nombre. Un competidor agrupado cambia de nombre
 * al fusionarse; sus ids, no.
 */
function rowKey(c: Competitor, idx: number): string {
  if ((c.empresa_ids?.length ?? 0) > 0) return `ids:${c.empresa_ids!.join("-")}`;
  if (c.nifs?.length) return `nifs:${c.nifs.join("-")}`;
  return `nombre:${c.nombre}:${idx}`;
}

export function CompetidoresTabla({
  filas,
  totalEmpresas,
  isLoading,
  search,
  sortKey,
  sortDir,
  onSort,
  selectedCompanies,
  onToggleCompare,
  onDrillDown,
}: {
  filas: Competitor[];
  /** Universo del que salen las filas visibles, para el pie de la tabla. */
  totalEmpresas: number;
  isLoading: boolean;
  search: string;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onSort: (key: SortKey) => void;
  selectedCompanies: string[];
  onToggleCompare: (nombre: string) => void;
  onDrillDown: (competitor: Competitor) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle className="text-base">Todos los Competidores</CardTitle>
          <p className="text-muted-foreground text-xs">Selecciona 2 empresas para comparar con radar</p>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : filas.length > 0 ? (
          <div className="overflow-x-auto">
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="text-muted-foreground border-b text-left">
                  <TableHead className="w-10 px-2 py-2 font-medium">
                    <span className="sr-only">Comparar</span>
                  </TableHead>
                  {TABLE_COLUMNS.map(({ key, label }) => (
                    <TableHead
                      key={key}
                      className="hover:text-foreground cursor-pointer px-3 py-2 font-medium whitespace-nowrap select-none"
                      tabIndex={0}
                      role="columnheader"
                      aria-sort={sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                      onClick={() => onSort(key)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") onSort(key);
                      }}
                    >
                      <span className="inline-flex items-center gap-1">
                        {label}
                        {sortKey === key ? (
                          sortDir === "asc" ? (
                            <ArrowUp className="text-primary h-3 w-3" />
                          ) : (
                            <ArrowDown className="text-primary h-3 w-3" />
                          )
                        ) : (
                          <ArrowUpDown className="h-3 w-3 opacity-40" />
                        )}
                      </span>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((c, idx) => (
                  <CompetitorRow
                    key={rowKey(c, idx)}
                    competitor={c}
                    selected={selectedCompanies.includes(c.nombre)}
                    onToggleCompare={onToggleCompare}
                    onDrillDown={onDrillDown}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-muted-foreground py-8 text-center">
            {search ? "No se encontraron competidores" : "Sin datos disponibles"}
          </p>
        )}
        {!isLoading && filas.length > 0 && (
          <>
            <Separator className="my-3" />
            <p className="text-muted-foreground text-xs">
              Mostrando {filas.length} de {totalEmpresas} competidores
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
