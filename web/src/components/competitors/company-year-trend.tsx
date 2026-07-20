"use client";

import { Badge } from "@/components/ui/badge";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import type { CompanyYear } from "./company-profile-types";

interface CompanyYearTrendProps {
  rows: CompanyYear[];
  compact?: boolean;
}

function deltaLabel(current: number, previous: number): string {
  if (previous === 0) return current === 0 ? "Sin cambio" : "Sin base comparable";
  const delta = ((current - previous) / previous) * 100;
  return `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}% interanual`;
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

  const latest = sorted.at(-1);
  const previous = sorted.at(-2);
  const isPartialYear = latest?.anio === currentYear;
  const delta =
    latest && previous && !isPartialYear
      ? ((latest.importe - previous.importe) / Math.max(previous.importe, 1)) * 100
      : null;
  const DeltaIcon = delta == null ? Minus : delta >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="space-y-5">
      {!compact && latest ? (
        <div className="bg-muted/45 flex flex-wrap items-center justify-between gap-3 rounded-lg px-4 py-3">
          <div>
            <p className="text-muted-foreground text-xs font-medium tracking-[0.16em] uppercase">
              Último ejercicio observado
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums">{formatCurrency(latest.importe)}</p>
          </div>
          <div className="flex items-center gap-2">
            {isPartialYear ? (
              <Badge variant="secondary">Año en curso · dato parcial</Badge>
            ) : previous ? (
              <Badge
                variant="outline"
                className={cn(
                  "gap-1",
                  delta != null && delta >= 0
                    ? "border-emerald-500/30 text-emerald-700 dark:text-emerald-300"
                    : "border-amber-500/30 text-amber-700 dark:text-amber-300",
                )}
              >
                <DeltaIcon className="h-3.5 w-3.5" aria-hidden="true" />
                {deltaLabel(latest.importe, previous.importe)}
              </Badge>
            ) : null}
          </div>
        </div>
      ) : null}

      <div
        className={cn("grid items-end gap-2", compact ? "h-36" : "h-64")}
        style={{ gridTemplateColumns: `repeat(${sorted.length}, minmax(34px, 1fr))` }}
        role="img"
        aria-label="Evolución anual del importe adjudicado"
      >
        {sorted.map((row) => {
          const height = Math.max(5, (row.importe / maxAmount) * 100);
          return (
            <div key={row.anio} className="group flex h-full min-w-0 flex-col justify-end gap-2">
              {!compact ? (
                <div className="text-center text-xs font-medium tabular-nums opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                  {formatCurrency(row.importe)}
                </div>
              ) : null}
              <div className="bg-muted/55 relative flex min-h-0 flex-1 items-end rounded-md">
                <div
                  className="bg-primary/80 group-hover:bg-primary w-full rounded-md transition-[height,background-color]"
                  style={{ height: `${height}%` }}
                  title={`${row.anio}: ${formatCurrency(row.importe)}, ${formatNumber(row.contratos)} adjudicaciones`}
                />
              </div>
              <div className="text-center">
                <p className="text-xs font-semibold tabular-nums">{row.anio}</p>
                {!compact ? (
                  <p className="text-muted-foreground mt-0.5 text-[11px]">{formatNumber(row.contratos)} adj.</p>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      <table className="sr-only">
        <caption>Evolución anual de adjudicaciones</caption>
        <thead>
          <tr>
            <th>Año</th>
            <th>Adjudicaciones</th>
            <th>Importe</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.anio}>
              <td>{row.anio}</td>
              <td>{row.contratos}</td>
              <td>{row.importe}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
