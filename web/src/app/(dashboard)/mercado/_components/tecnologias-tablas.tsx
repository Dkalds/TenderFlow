"use client";

/**
 * La tabla agregada de tecnologías (con su buscador local) y la rejilla de las
 * veinte licitaciones con más score.
 *
 * El buscador filtra en cliente sobre lo que ya vino: el endpoint devuelve el
 * agregado completo, así que no hay nada que volver a pedir.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Pista } from "@/components/ui/pista";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { Search } from "lucide-react";

import type { ScoredItem, TecnologiaItem } from "../_hooks/use-tecnologias-view";

export function TecnologiasTabla({
  filas,
  filter,
  onFilterChange,
  isLoading,
}: {
  filas: TecnologiaItem[];
  filter: string;
  onFilterChange: (value: string) => void;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title="Todas las tecnologías" />
      <div className="relative mb-3 max-w-sm">
        <Search
          className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          placeholder="Buscar tecnología…"
          aria-label="Buscar tecnología"
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          className="pl-8"
        />
      </div>
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tecnología</TableHead>
              <TableHead className="text-right">Licitaciones</TableHead>
              <TableHead className="text-right">Importe</TableHead>
              <TableHead className="text-right">Adjudicadas</TableHead>
              <TableHead className="text-right">% del total</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((item, idx) => (
              <TableRow key={idx}>
                <TableCell className="font-medium">{item.tecnologia}</TableCell>
                <TableCell numeric>{formatNumber(item.count)}</TableCell>
                <TableCell numeric>{formatCurrency(item.importe)}</TableCell>
                <TableCell numeric>{formatPercent(item.pct_adjudicado)}</TableCell>
                <TableCell numeric>{formatPercent(item.pct)}</TableCell>
              </TableRow>
            ))}
            {filas.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  {filter
                    ? "Ninguna tecnología coincide con la búsqueda."
                    : "Ninguna licitación del ámbito actual tiene tecnología identificada."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}

export function TecnologiasTopScore({ items }: { items: ScoredItem[] }) {
  return (
    <Panel>
      <PanelTitle title="Las 20 licitaciones mejor puntuadas" />
      <ul className="grid gap-3 sm:grid-cols-2">
        {items.slice(0, 20).map((item, idx) => (
          <li key={idx} className="space-y-1 rounded-md border border-border/60 p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="font-mono text-tf-micro text-muted-foreground">{item.id}</span>
              <Badge variant={item.score >= 80 ? "default" : "secondary"} size="sm">
                {item.score}
              </Badge>
            </div>
            <Pista contenido={item.titulo}>
              <p className="line-clamp-2 text-tf-body font-medium">{item.titulo}</p>
            </Pista>
            <div className="flex items-center justify-between gap-2 text-tf-meta text-muted-foreground">
              <span>{formatCurrency(item.importe)}</span>
              {item.organo_contratacion && (
                <span className="max-w-[50%] truncate">{item.organo_contratacion}</span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
