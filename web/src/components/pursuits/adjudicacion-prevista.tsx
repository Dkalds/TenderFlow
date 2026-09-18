"use client";

/**
 * F4.4 — fecha prevista de adjudicación, como `<dt>/<dd>` del contexto de la
 * oportunidad.
 *
 * Una **estimación** se enseña como intervalo p25–p75 con su base (`n`
 * adjudicaciones del órgano) y la marca «estimación»; sólo un **hito**
 * publicado se enseña como fecha. Sin base, «Sin estimación» — nunca una
 * fecha con asterisco (ADR-014).
 */
import type { AdjudicacionPrevista } from "@/lib/adjudicacion-prevista";
import { textoAdjudicacion } from "@/lib/adjudicacion-prevista";

export function AdjudicacionPrevistaDato({
  prevista,
}: {
  prevista: AdjudicacionPrevista | null | undefined;
}) {
  const texto = textoAdjudicacion(prevista);
  return (
    <div>
      <dt className="text-[10.5px] text-muted-foreground">Adjudicación prevista</dt>
      <dd className="font-semibold">
        {texto.valor}
        {texto.metodo === "estimacion" ? (
          <span className="ml-1.5 inline-flex h-[18px] items-center rounded-sm border border-border/70 bg-muted/60 px-1.5 align-middle text-[10px] font-medium text-muted-foreground">
            estimación
          </span>
        ) : null}
      </dd>
      <dd className="mt-0.5 text-[10.5px] leading-[1.45] font-normal text-muted-foreground">
        {texto.base}
      </dd>
    </div>
  );
}
