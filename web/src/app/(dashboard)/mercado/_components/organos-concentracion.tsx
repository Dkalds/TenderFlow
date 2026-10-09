"use client";

/**
 * Cuánto mercado se llevan los 10 primeros órganos, como waffle: 100 casillas,
 * las llenas en primario. Se lee de un vistazo y conmuta con la medida.
 *
 * Por licitaciones la cifra es la de la API sobre todo el ámbito. Por importe
 * no hay cifra de la API: se calcula sobre la lista recibida —los 50 órganos
 * más activos— y el panel lo dice como parcial en vez de presentarlo como total.
 */

import { Panel, PanelLoading, PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { valorOEmpty } from "@/lib/cobertura";
import { cn, EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { MetricaOrganos } from "../_hooks/use-organos-view";

const CASILLAS = Array.from({ length: 100 }, (_, i) => i);

export function OrganosConcentracion({
  concentracion,
  metrica,
  nItems,
  totalOrganos,
  importeTotal,
  importeMedio,
  isLoading,
}: {
  concentracion: { pct: number | null; parcial: boolean };
  metrica: MetricaOrganos;
  /** Órganos de la lista recibida: el universo de la cifra parcial. */
  nItems: number;
  totalOrganos: number | null;
  importeTotal: number | null;
  importeMedio: number | null;
  isLoading: boolean;
}) {
  const pct = concentracion.pct;
  const llenas = pct == null ? 0 : Math.max(0, Math.min(100, Math.round(pct)));
  const deQue = metrica === "count" ? "de las licitaciones" : "del importe";
  const restantes = totalOrganos != null && totalOrganos > 10 ? totalOrganos - 10 : null;
  const descripcion =
    pct == null
      ? `Sin cifra de concentración ${deQue} para el ámbito actual.`
      : `Los 10 primeros órganos concentran el ${formatPercent(pct, 0)} ${deQue}${
          concentracion.parcial ? ` entre los ${formatNumber(nItems)} órganos más activos` : ""
        }.`;

  return (
    <Panel className="flex flex-col gap-4">
      <PanelTitle
        title="Concentración"
        hint={`cada casilla es el 1 % ${deQue}`}
        className="mb-0"
      />
      {isLoading ? (
        <PanelLoading height={300} />
      ) : (
        <>
          <div className="flex items-baseline gap-3">
            <span className="tf-tnum font-display text-tf-hero font-semibold text-primary">
              {valorOEmpty(pct, (v) => formatPercent(v, 0))}
            </span>
            <span className="max-w-[14rem] text-tf-body text-muted-foreground">
              {pct == null
                ? "sin cifra para el ámbito actual"
                : `${deQue} lo concentran 10 órganos${concentracion.parcial ? `, entre los ${formatNumber(nItems)} más activos` : ""}`}
            </span>
          </div>
          {/* Una imagen con su texto alternativo: la rejilla no es navegable y
              no tiene por qué serlo. */}
          <div
            role="img"
            aria-label={descripcion}
            className="grid w-56 max-w-full grid-cols-10 gap-1"
          >
            {CASILLAS.map((i) => (
              <span
                key={i}
                className={cn("aspect-square rounded-sm", i < llenas ? "bg-primary" : "bg-muted")}
              />
            ))}
          </div>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-tf-micro text-muted-foreground">
            <li className="flex items-center gap-1.5">
              <span aria-hidden="true" className="h-2.5 w-2.5 flex-none rounded-sm bg-primary" />
              Los 10 primeros órganos
            </li>
            <li className="flex items-center gap-1.5">
              <span aria-hidden="true" className="h-2.5 w-2.5 flex-none rounded-sm bg-muted" />
              {restantes != null ? `Los otros ${formatNumber(restantes)}` : "El resto"}
            </li>
          </ul>
          <StatStrip columns={2} className="mt-auto">
            <StatCell label="Importe total" value={valorOEmpty(importeTotal, formatCurrency)} />
            <StatCell
              label="Importe medio"
              value={importeMedio != null ? formatCurrency(importeMedio) : EMPTY}
              hint="por licitación del ámbito"
            />
          </StatStrip>
        </>
      )}
    </Panel>
  );
}
