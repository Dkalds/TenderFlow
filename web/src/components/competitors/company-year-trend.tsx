"use client";

import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

import type { CompanyYear } from "./company-profile-types";

interface CompanyYearTrendProps {
  rows: CompanyYear[];
  compact?: boolean;
}

function amountDelta(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

export function CompanyYearTrend({ rows, compact = false }: CompanyYearTrendProps) {
  const sorted = [...rows].sort((a, b) => a.anio - b.anio);
  const maxAmount = Math.max(...sorted.map((row) => row.importe), 1);
  const currentYear = new Date().getFullYear();

  if (sorted.length === 0) {
    return (
      <div className="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm">
        No hay años con actividad dentro del periodo seleccionado.
      </div>
    );
  }

  const latest = sorted.at(-1)!;
  const currentPartial = latest.anio === currentYear ? latest : null;
  const latestCompleted = currentPartial ? sorted.at(-2) : latest;
  const completedIndex = latestCompleted ? sorted.findIndex((row) => row.anio === latestCompleted.anio) : -1;
  const previousCompleted = completedIndex > 0 ? sorted[completedIndex - 1] : null;
  const delta =
    latestCompleted && previousCompleted ? amountDelta(latestCompleted.importe, previousCompleted.importe) : null;
  const DeltaIcon = delta == null ? Minus : delta >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="space-y-5">
      {!compact ? (
        <div className="bg-muted/35 grid gap-3 rounded-lg px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center">
          <div className="flex flex-wrap items-end gap-x-7 gap-y-3">
            {latestCompleted ? (
              <div>
                <p className="text-muted-foreground text-xs font-medium tracking-[0.12em] uppercase">
                  Último ejercicio completo · {latestCompleted.anio}
                </p>
                <p className="mt-1 text-lg font-semibold tabular-nums">{formatCurrency(latestCompleted.importe)}</p>
                <p className="text-muted-foreground text-xs">
                  {formatNumber(latestCompleted.contratos)} adjudicaciones
                </p>
              </div>
            ) : null}
            {currentPartial ? (
              <div>
                <Badge variant="secondary">Año en curso · dato parcial</Badge>
                <p className="mt-1.5 text-sm font-semibold tabular-nums">
                  {formatCurrency(currentPartial.importe)} · {formatNumber(currentPartial.contratos)} adj.
                </p>
              </div>
            ) : null}
          </div>
          {latestCompleted && previousCompleted ? (
            <Badge
              variant="outline"
              className={cn(
                "w-fit gap-1",
                delta != null && delta >= 0
                  ? "border-primary/30 text-primary"
                  : "border-amber-500/30 text-amber-700 dark:text-amber-300",
              )}
            >
              <DeltaIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {delta == null ? "Sin base comparable" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}% interanual`}
            </Badge>
          ) : null}
        </div>
      ) : currentPartial ? (
        <div className="flex justify-end">
          <Badge variant="secondary">Año en curso · dato parcial</Badge>
        </div>
      ) : null}

      <div className="overflow-x-auto pb-1">
        <ol
          className={cn("grid w-full items-end gap-2", compact ? "h-36" : "h-64")}
          style={{
            gridTemplateColumns: `repeat(${sorted.length}, minmax(${compact ? 42 : 54}px, 1fr))`,
            minWidth: `${sorted.length * (compact ? 48 : 64)}px`,
          }}
          aria-label="Evolución anual del importe adjudicado"
        >
          {sorted.map((row) => {
            const height = Math.max(5, (row.importe / maxAmount) * 100);
            const isCurrentPartial = row.anio === currentYear;
            return (
              <li
                key={row.anio}
                className="group flex h-full min-w-0 flex-col justify-end gap-2 rounded-sm"
                title={`${row.anio}: ${formatCurrency(row.importe)}, ${formatNumber(row.contratos)} adjudicaciones${isCurrentPartial ? ", dato parcial" : ""}`}
              >
                {!compact ? (
                  <div className="text-center text-xs font-medium tabular-nums opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    {formatCurrency(row.importe)}
                  </div>
                ) : null}
                <div className="bg-muted/55 relative flex min-h-0 flex-1 items-end rounded-md">
                  <div
                    className={cn(
                      "w-full rounded-md transition-[height,background-color]",
                      isCurrentPartial
                        ? "bg-primary/45 ring-primary/50 ring-1 ring-inset"
                        : "bg-primary/80 group-hover:bg-primary",
                    )}
                    style={{ height: `${height}%` }}
                    aria-hidden="true"
                  />
                </div>
                <div className="text-center">
                  <p className="text-xs font-semibold tabular-nums">{row.anio}</p>
                  <p className="text-muted-foreground mt-0.5 text-[11px]">{formatNumber(row.contratos)} adj.</p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <table className="sr-only">
        <caption>Evolución anual de adjudicaciones</caption>
        <thead>
          <tr>
            <th>Año</th>
            <th>Adjudicaciones</th>
            <th>Importe</th>
            <th>Estado</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.anio}>
              <td>{row.anio}</td>
              <td>{row.contratos}</td>
              <td>{row.importe}</td>
              <td>{row.anio === currentYear ? "Año en curso, dato parcial" : "Ejercicio completo"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
