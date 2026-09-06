"use client";

/**
 * Buscador del maestro y tabla de resultados: por nombre canónico, alias o NIF,
 * ordenado por importe adjudicado total.
 */

import { Eye, EyeOff, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrency, formatNumber } from "@/lib/utils";
import type { EmpresaRow } from "../_lib/types";

interface Props {
  search: string;
  onSearchChange: (value: string) => void;
  items: EmpresaRow[];
  isLoading: boolean;
  selectedId: number | null;
  onSelect: (empresaId: number) => void;
  watchedIds: Set<number>;
  onToggleWatch: (empresaId: number, watched: boolean) => void;
  toggleDisabled: boolean;
}

export function EmpresasBuscador({
  search,
  onSearchChange,
  items,
  isLoading,
  selectedId,
  onSelect,
  watchedIds,
  onToggleWatch,
  toggleDisabled,
}: Props) {
  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>Buscador</CardTitle>
          <CardDescription>
            Por nombre canónico, alias o NIF. Ordenado por importe adjudicado total.
          </CardDescription>
        </div>
        <div className="relative w-full sm:w-80">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Indra, B28599033, accenture…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-8"
          />
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[320px] w-full" />
        ) : items.length === 0 ? (
          <EmptyState
            icon={Search}
            title="Sin resultados"
            hint="Prueba con otro nombre o NIF, o ejecuta el backfill del maestro."
          />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Empresa</TableHead>
                  <TableHead>NIF</TableHead>
                  <TableHead className="text-right">Contratos</TableHead>
                  <TableHead className="text-right">Importe total</TableHead>
                  <TableHead className="w-24 text-right">Vigilar</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((e) => {
                  const watched = watchedIds.has(e.empresa_id);
                  return (
                    <TableRow
                      key={e.empresa_id}
                      className={
                        selectedId === e.empresa_id
                          ? "cursor-pointer bg-primary/5"
                          : "cursor-pointer"
                      }
                      onClick={() => onSelect(e.empresa_id)}
                    >
                      <TableCell className="max-w-[300px]">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-sm font-medium">{e.nombre_canonico}</span>
                          {e.es_ute ? <Badge variant="outline">UTE</Badge> : null}
                          {e.es_pyme ? <Badge variant="secondary">PYME</Badge> : null}
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {e.nif_canonico ?? "—"}
                      </TableCell>
                      <TableCell className="text-right text-sm">
                        {formatNumber(e.n_adjudicaciones)}
                      </TableCell>
                      <TableCell className="text-right text-sm font-medium">
                        {formatCurrency(e.importe_total)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={watched ? "Dejar de vigilar" : "Vigilar empresa"}
                          disabled={toggleDisabled}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            onToggleWatch(e.empresa_id, watched);
                          }}
                        >
                          {watched ? (
                            <Eye className="h-4 w-4 text-primary" />
                          ) : (
                            <EyeOff className="h-4 w-4 text-muted-foreground" />
                          )}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
