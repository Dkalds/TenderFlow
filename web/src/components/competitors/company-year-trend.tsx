"use client";

import { ROTULO_DATO } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Pista } from "@/components/ui/pista";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

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
      <p role="status" className="py-6 text-center text-tf-meta text-muted-foreground">
        No hay años con actividad dentro del periodo seleccionado.
      </p>
    );
  }

  const latest = sorted.at(-1)!;
  const currentPartial = latest.anio === currentYear ? latest : null;
  const latestCompleted = currentPartial ? sorted.at(-2) : latest;
  const completedIndex = latestCompleted ? sorted.findIndex((row) => row.anio === latestCompleted.anio) : -1;
  const previousCompleted = completedIndex > 0 ? sorted[completedIndex - 1] : null;
  const delta =
    latestCompleted && previousCompleted ? amountDelta(latestCompleted.importe, previousCompleted.importe) : null;

  return (
    <div className="space-y-5">
      {!compact ? (
        <div className="grid gap-3 rounded-md bg-muted/40 px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center">
          <div className="flex flex-wrap items-end gap-x-7 gap-y-3">
            {latestCompleted ? (
              <div>
                <p className={ROTULO_DATO}>Último ejercicio completo · {latestCompleted.anio}</p>
                <p className="mt-1 text-tf-title font-semibold">{formatCurrency(latestCompleted.importe)}</p>
                <p className="text-tf-meta text-muted-foreground">
                  {formatNumber(latestCompleted.contratos)} adjudicaciones
                </p>
              </div>
            ) : null}
            {currentPartial ? (
              <div>
                <Badge variant="secondary">Año en curso · dato parcial</Badge>
                <p className="mt-1.5 text-tf-body font-semibold">
                  {formatCurrency(currentPartial.importe)} · {formatNumber(currentPartial.contratos)} adjudicaciones
                </p>
              </div>
            ) : null}
          </div>
          {latestCompleted && previousCompleted ? (
            // Neutro: que un competidor crezca no es ni bueno ni malo para
            // quien lo mira.
            <Badge variant="outline" className="w-fit">
              {delta == null
                ? "Sin base comparable"
                : `${delta >= 0 ? "+" : ""}${formatPercent(delta)} interanual`}
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
            // `Pista` en vez de `title`: el lector ya tiene la tabla `sr-only`
            // de abajo con las mismas cifras, así que la barra no necesita ser
            // focusable para contarlas.
            return (
              <Pista
                key={row.anio}
                contenido={`${row.anio}: ${formatCurrency(row.importe)}, ${formatNumber(row.contratos)} adjudicaciones${isCurrentPartial ? ", dato parcial" : ""}`}
              >
                <li className="group flex h-full min-w-0 flex-col justify-end gap-2 rounded-sm">
                  {!compact ? (
                    <div className="text-center text-tf-micro font-medium opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                      {formatCurrency(row.importe)}
                    </div>
                  ) : null}
                  <div className="relative flex min-h-0 flex-1 items-end rounded-sm bg-muted">
                    {/* Sin transición de altura: es una medida, no algo que
                        se mueva al cambiar de periodo. */}
                    <div
                      className={cn(
                        "w-full rounded-sm transition-colors",
                        isCurrentPartial
                          ? "bg-primary/30 ring-1 ring-inset ring-primary/50"
                          : "bg-primary/80 group-hover:bg-primary",
                      )}
                      style={{ height: `${height}%` }}
                      aria-hidden="true"
                    />
                  </div>
                  <div className="text-center">
                    <p className="text-tf-meta font-semibold">{row.anio}</p>
                    <p className="mt-0.5 text-tf-micro text-muted-foreground">{formatNumber(row.contratos)} adj.</p>
                  </div>
                </li>
              </Pista>
            );
          })}
        </ol>
      </div>

      {/* `sr-only` en un envoltorio y no en la tabla: una tabla no encoge por
          debajo de su contenido, así que seguía midiendo su ancho entero fuera
          de pantalla y ensanchaba la caja con scroll que la contuviera. */}
      <div className="sr-only">
        <table>
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
    </div>
  );
}
