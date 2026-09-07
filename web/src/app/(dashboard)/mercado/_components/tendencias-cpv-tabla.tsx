"use client";

/**
 * Tabla Top CPVs: el mismo ranking del gráfico, con la fila como atajo para
 * marcar o desmarcar ese CPV en el multilínea de arriba.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getSeriesColor } from "@/lib/chart-colors";
import { formatCurrency, formatNumber } from "@/lib/utils";

import type { CpvTableRow } from "../_hooks/use-tendencias-cpv-view";

export function TendenciasCpvTabla({
  filas,
  onToggle,
  isLoading,
}: {
  filas: CpvTableRow[];
  onToggle: (cpv: string) => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top CPVs</CardTitle>
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
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="border-b">
                  <TableHead className="text-left py-2 pr-4 font-medium text-muted-foreground">#</TableHead>
                  <TableHead className="text-left py-2 pr-4 font-medium text-muted-foreground">CPV</TableHead>
                  <TableHead className="text-right py-2 pr-4 font-medium text-muted-foreground">Licitaciones</TableHead>
                  <TableHead className="text-right py-2 font-medium text-muted-foreground">Importe Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((row) => (
                  <TableRow
                    key={row.cpv}
                    className="border-b last:border-0 hover:bg-muted/50 cursor-pointer transition-colors"
                    tabIndex={0}
                    role="row"
                    onClick={() => onToggle(row.cpv)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onToggle(row.cpv); }}
                  >
                    <TableCell className="py-2 pr-4 tabular-nums text-muted-foreground">{row.rank}</TableCell>
                    <TableCell className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <div
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: getSeriesColor(row.rank - 1) }}
                        />
                        {row.cpv}
                      </div>
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">{formatNumber(row.count)}</TableCell>
                    <TableCell className="py-2 text-right tabular-nums">{formatCurrency(row.importe)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}
