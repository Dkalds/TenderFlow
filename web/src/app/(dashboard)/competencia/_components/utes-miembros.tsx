"use client";

/**
 * La tabla completa de miembros de UTE, con su buscador.
 *
 * El pie declara el universo del que salen las filas visibles («N de M»), que
 * es lo que permite leer el filtro como filtro y no como el total.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { Handshake, Search } from "lucide-react";

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
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Handshake className="h-4 w-4" />
            Todas las UTEs
          </CardTitle>
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar miembro…"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-8"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : filas.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="text-left text-muted-foreground">
                  <TableHead>#</TableHead>
                  <TableHead>Nombre</TableHead>
                  <TableHead>Participaciones</TableHead>
                  <TableHead>Importe</TableHead>
                  <TableHead>Importe Medio</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((m, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="text-muted-foreground tabular-nums">{idx + 1}</TableCell>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        {m.nombre}
                        <Badge variant="outline" className="text-xs">UTE</Badge>
                      </div>
                    </TableCell>
                    <TableCell className="tabular-nums">{formatNumber(m.count)}</TableCell>
                    <TableCell className="tabular-nums">{formatCurrency(m.importe)}</TableCell>
                    <TableCell className="tabular-nums">
                      {m.count > 0 ? formatCurrency(m.importe / m.count) : "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Separator className="my-3" />
            <p className="text-xs text-muted-foreground">
              Mostrando {filas.length} de {totalMiembros} miembros
            </p>
          </div>
        ) : (
          <p className="py-8 text-center text-muted-foreground">
            {search ? "No se encontraron miembros" : "Sin datos de UTEs disponibles"}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
