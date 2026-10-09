"use client";

/**
 * Cabecera de UTE: el titular de dato y la exportación de la sección.
 *
 * El titular es la conclusión, no un rótulo: «En UTE, el contrato medio es de
 * 1.900.000 €; en solitario, de 560.000 €». Son las dos cifras de la API
 * dichas tal cual, sin el «tantas veces más» que saldría de dividirlas aquí.
 * Mientras falte alguna —o no haya contratos sobre los que hacer la media—, el
 * titular se queda en la pregunta de la vista.
 */

import { ExportPopover } from "@/components/export-popover";
import type { Schemas } from "@/lib/api-types";
import { formatCompactCurrency, formatCurrency, formatNumber } from "@/lib/utils";

import { importeMedioConDato } from "../_hooks/utes-series";

export function UtesCabecera({
  kpis,
  isLoading,
}: {
  kpis: Schemas["UTEKpis"] | undefined;
  isLoading: boolean;
}) {
  const enUte = isLoading ? null : importeMedioConDato(kpis?.ticket_medio_ute);
  const enSolitario = isLoading ? null : importeMedioConDato(kpis?.ticket_medio_individual);
  const resumen =
    !isLoading && kpis != null
      ? `${formatNumber(kpis.total_ute)} adjudicaciones a UTE · ${formatCurrency(kpis.importe_ute)}. `
      : "";

  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="sr-only">UTE</h1>
        <h2 className="font-display text-tf-title font-semibold">
          {enUte != null && enSolitario != null ? (
            <>
              En UTE, el contrato medio es de{" "}
              <span className="tf-tnum text-primary">{formatCompactCurrency(enUte)}</span>; en
              solitario, de <span className="tf-tnum">{formatCompactCurrency(enSolitario)}</span>
            </>
          ) : (
            "Con quién se alía cada competidor para ganar"
          )}
        </h2>
        <p className="mt-1 text-tf-meta text-muted-foreground">
          {resumen}
          Pulsa una empresa en la red para quedarte con sus alianzas.
        </p>
      </div>

      <ExportPopover extraParams={{ section: "utes" }} label="Exportar UTE" />
    </div>
  );
}
