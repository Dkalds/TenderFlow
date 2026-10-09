"use client";

/**
 * La tira de cifras de UTE: cuántas adjudicaciones y cuánto importe, cada una
 * frente a lo adjudicado en solitario, y el contrato medio de las dos formas
 * como barras pareadas.
 *
 * Las barras sustituyen a la tabla «UTE frente a contrato en solitario»: la
 * comparación es de dos cifras y se lee antes como dos largos que como dos
 * celdas. Cada barra va a escala de la mayor de las dos.
 */

import { ROTULO_DATO, StatCell, StatStrip } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api-types";
import { CHART_SERIES } from "@/lib/chart-colors";
import { valorOEmpty } from "@/lib/cobertura";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

import { barrasImporteMedio, type BarraImporteMedio } from "../_hooks/utes-series";
import { BarraPct } from "./dibujos";

/** UTE en el color de su serie; en solitario, en el gris de «el resto». */
const COLOR_BARRA: Record<BarraImporteMedio["clave"], string> = {
  ute: CHART_SERIES[0],
  solitario: CHART_SERIES[7],
};

function BarrasImporteMedio({ barras }: { barras: BarraImporteMedio[] }) {
  return (
    <dl className="space-y-1.5">
      {barras.map((barra) => (
        <div key={barra.clave} className="flex items-center gap-2.5">
          <dt className="w-20 flex-none text-tf-meta font-medium">{barra.etiqueta}</dt>
          <dd className="flex min-w-0 flex-1 items-center gap-2.5">
            <BarraPct pct={barra.pct} color={COLOR_BARRA[barra.clave]} className="h-3.5 min-w-0 flex-1 rounded-sm" />
            <span
              className={cn(
                "tf-tnum w-24 flex-none text-right text-tf-body",
                barra.clave === "ute" ? "font-bold" : "font-semibold",
              )}
            >
              {valorOEmpty(barra.valor, formatCurrency)}
            </span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function UtesKpis({
  kpis,
  comparativa,
  isLoading,
}: {
  kpis: Schemas["UTEKpis"] | undefined;
  comparativa: Schemas["UTEComparacion"] | undefined;
  isLoading: boolean;
}) {
  const solitario = comparativa?.individual;
  return (
    <StatStrip columns={4}>
      <StatCell
        label="Adjudicaciones a UTE"
        value={formatNumber(kpis?.total_ute)}
        hint={solitario ? `frente a ${formatNumber(solitario.count)} en solitario` : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Importe en UTE"
        value={formatCurrency(kpis?.importe_ute)}
        hint={solitario ? `frente a ${formatCurrency(solitario.importe_total)} en solitario` : undefined}
        loading={isLoading}
      />
      <div data-slot="stat-cell" className="col-span-2 min-w-0 bg-card px-3.5 py-2.5">
        <div className={cn("mb-2", ROTULO_DATO)}>Importe medio por contrato</div>
        {isLoading ? <Skeleton className="h-9 w-full rounded-sm" /> : <BarrasImporteMedio barras={barrasImporteMedio(kpis)} />}
      </div>
    </StatStrip>
  );
}
