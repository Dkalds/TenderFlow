"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn, formatNumber } from "@/lib/utils";
import { ArrowUpDown } from "lucide-react";
import type { CompareResponse } from "./types";

interface PeriodComparisonProps {
  comparar: boolean;
  setComparar: (v: boolean) => void;
  rango: { desde: string | null; hasta: string | null };
  rangoB: { desde: string | null; hasta: string | null };
  compare: { data: CompareResponse | undefined; isLoading: boolean };
}

export function PeriodComparison({
  comparar,
  setComparar,
  rango,
  rangoB,
  compare,
}: PeriodComparisonProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Comparar Periodos</CardTitle>
          <Button
            variant={comparar ? "default" : "outline"}
            size="sm"
            onClick={() => setComparar(!comparar)}
          >
            <ArrowUpDown className="mr-2 h-4 w-4" />
            {comparar ? "Desactivar" : "Comparar"}
          </Button>
        </div>
      </CardHeader>
      {comparar && (
        <CardContent>
          {!rango.desde || !rangoB.desde ? (
            <p className="text-sm text-muted-foreground py-4">
              Selecciona dos rangos de fechas en los filtros globales para comparar.
            </p>
          ) : compare.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : compare.data ? (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b">
                    <TableHead className="text-left py-2 font-medium">Metrica</TableHead>
                    <TableHead className="text-right py-2 font-medium">Periodo A</TableHead>
                    <TableHead className="text-right py-2 font-medium">Periodo B</TableHead>
                    <TableHead className="text-right py-2 font-medium">Delta %</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.keys(compare.data.deltas).map((key) => (
                    <TableRow key={key} className="border-b last:border-0">
                      <TableCell className="py-2 text-muted-foreground">
                        {key.replace(/_/g, " ")}
                      </TableCell>
                      <TableCell className="py-2 text-right tabular-nums">
                        {formatNumber(compare.data!.period_a[key])}
                      </TableCell>
                      <TableCell className="py-2 text-right tabular-nums">
                        {formatNumber(compare.data!.period_b[key])}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "py-2 text-right tabular-nums font-medium",
                          compare.data!.deltas[key] >= 0 ? "text-green-600" : "text-red-600",
                        )}
                      >
                        {compare.data!.deltas[key] >= 0 ? "+" : ""}
                        {compare.data!.deltas[key].toFixed(1)}%
                        <span className="sr-only">
                          {compare.data!.deltas[key] >= 0 ? "(subida)" : "(bajada)"}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      )}
    </Card>
  );
}
