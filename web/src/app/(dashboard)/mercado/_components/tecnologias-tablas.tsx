"use client";

/**
 * La tabla agregada de tecnologías (con su buscador local) y la rejilla de las
 * veinte licitaciones con más score.
 *
 * El buscador filtra en cliente sobre lo que ya vino: el endpoint devuelve el
 * agregado completo, así que no hay nada que volver a pedir.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { Search, Star } from "lucide-react";

import type { ScoredItem, TecnologiaItem } from "../_hooks/use-tecnologias-view";

const TH_NUM = "pb-2 pr-4 text-right font-medium text-muted-foreground";

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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Todas las Tecnologías</CardTitle>
        <div className="relative mt-2">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar tecnología…"
            value={filter}
            onChange={(e) => onFilterChange(e.target.value)}
            className="max-w-sm pl-9"
          />
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="border-b text-left">
                  <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Tecnología</TableHead>
                  <TableHead className={TH_NUM}>Cantidad</TableHead>
                  <TableHead className={TH_NUM}>Importe</TableHead>
                  <TableHead className={TH_NUM}>% Adj.</TableHead>
                  <TableHead className="pb-2 text-right font-medium text-muted-foreground">%</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((item, idx) => (
                  <TableRow key={idx} className="border-b border-border/50 hover:bg-muted/50">
                    <TableCell className="py-2 pr-4 font-medium">{item.tecnologia}</TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">{formatNumber(item.count)}</TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">{formatCurrency(item.importe)}</TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">{formatPercent(item.pct_adjudicado)}</TableCell>
                    <TableCell className="py-2 text-right tabular-nums">{formatPercent(item.pct)}</TableCell>
                  </TableRow>
                ))}
                {filas.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
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

export function TecnologiasTopScore({ items }: { items: ScoredItem[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Star className="h-4 w-4" />
          Top 20 Licitaciones por Score
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2">
          {items.slice(0, 20).map((item, idx) => (
            <div key={idx} className="space-y-1 rounded-lg border border-border p-3">
              <div className="flex items-start justify-between gap-2">
                <span className="text-xs tabular-nums text-muted-foreground">{item.id}</span>
                <Badge variant={item.score >= 80 ? "default" : "secondary"}>{item.score}</Badge>
              </div>
              <p className="line-clamp-2 text-sm font-medium" title={item.titulo}>
                {item.titulo}
              </p>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{formatCurrency(item.importe)}</span>
                {item.organo_contratacion && (
                  <span className="max-w-[50%] truncate">{item.organo_contratacion}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
