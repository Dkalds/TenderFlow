"use client";

/**
 * Tabla Top CPVs: el mismo ranking del gráfico, con la fila como atajo para
 * marcar o desmarcar ese CPV en el multilínea de arriba.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
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
    <Panel>
      <PanelTitle title="CPV con más importe" hint="Pulsa una fila para mostrarlo u ocultarlo en el gráfico" />
      <div>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : filas.length > 0 ? (
          <div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>CPV</TableHead>
                  <TableHead className="text-right">Licitaciones</TableHead>
                  <TableHead className="text-right">Importe total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((row) => (
                  <TableRow
                    key={row.cpv}
                    className="cursor-pointer"
                    tabIndex={0}
                    role="row"
                    onClick={() => onToggle(row.cpv)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onToggle(row.cpv); }}
                  >
                    <TableCell className="text-muted-foreground">{row.rank}</TableCell>
                    <TableCell className="font-mono">
                      <div className="flex items-center gap-2">
                        <div
                          aria-hidden="true"
                          className="h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: getSeriesColor(row.rank - 1) }}
                        />
                        {row.cpv}
                      </div>
                    </TableCell>
                    <TableCell numeric>{formatNumber(row.count)}</TableCell>
                    <TableCell numeric>{formatCurrency(row.importe)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <PanelEmpty title="Ningún CPV" hint="Ningún CPV con licitaciones en el ámbito actual. Amplía las fechas o quita filtros." />
        )}
      </div>
    </Panel>
  );
}
