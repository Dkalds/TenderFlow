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
import { ROTULO_DATO } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
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
      <dt className={ROTULO_DATO}>Adjudicación prevista</dt>
      <dd className="font-semibold">
        {texto.valor}
        {texto.metodo === "estimacion" ? (
          <Badge size="sm" className="ml-1.5 align-middle">
            Estimación
          </Badge>
        ) : null}
      </dd>
      <dd className="mt-0.5 text-tf-micro font-normal text-muted-foreground">{texto.base}</dd>
    </div>
  );
}
