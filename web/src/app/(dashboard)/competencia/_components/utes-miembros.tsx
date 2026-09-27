"use client";

/**
 * La tabla completa de miembros de UTE, con su buscador.
 *
 * El pie declara el universo del que salen las filas visibles («N de M»), que
 * es lo que permite leer el filtro como filtro y no como el total.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EMPTY, formatCurrency, formatNumber } from "@/lib/utils";
import { Search } from "lucide-react";

import type { TopMiembro } from "../_hooks/utes-types";

export function UtesMiembros({
  filas,
  totalMiembros,
  search,
  onSearchChange,
  isLoading,
}: {
  filas: TopMiembro[];
  /** Universo del que salen las filas visibles, para el pie de la tabla. */
  totalMiembros: number;
  search: string;
  onSearchChange: (value: string) => void;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        title="Miembros de UTE"
        actions={
          <div className="relative w-full sm:w-64">
            <Search
              className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              placeholder="Buscar miembro…"
              aria-label="Buscar miembro"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-8"
            />
          </div>
        }
      />
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : filas.length > 0 ? (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Nombre</TableHead>
                <TableHead className="text-right">Participaciones</TableHead>
                <TableHead className="text-right">Importe</TableHead>
                <TableHead className="text-right">Importe medio</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filas.map((m, idx) => (
                <TableRow key={idx}>
                  <TableCell className="text-muted-foreground">{idx + 1}</TableCell>
                  <TableCell className="font-medium">{m.nombre}</TableCell>
                  <TableCell numeric>{formatNumber(m.count)}</TableCell>
                  <TableCell numeric>{formatCurrency(m.importe)}</TableCell>
                  <TableCell numeric>{m.count > 0 ? formatCurrency(m.importe / m.count) : EMPTY}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 border-t border-border/60 pt-3 text-tf-meta text-muted-foreground">
            Mostrando {formatNumber(filas.length)} de {formatNumber(totalMiembros)} miembros
          </p>
        </>
      ) : (
        <PanelEmpty
          title={search ? "Ningún miembro coincide con la búsqueda" : "Ninguna UTE"}
          hint={
            search
              ? "Prueba con otro nombre."
              : "No hay UTE adjudicatarias en el ámbito actual. Amplía las fechas o quita filtros."
          }
        />
      )}
    </Panel>
  );
}
