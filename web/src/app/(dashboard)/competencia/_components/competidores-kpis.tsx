"use client";

/**
 * Los cuatro KPIs del mercado competitivo.
 *
 * «% Oferta única» recibe el mismo trato que en `/resumen`: con cobertura
 * insuficiente no se pinta un número atenuado, se dice qué falta. Un porcentaje
 * en gris sigue siendo un porcentaje en la cabeza de quien lo lee, y el
 * denominador (`cobertura_ofertas_pct`) lo manda la API precisamente para poder
 * abstenerse.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import { EMPTY, formatNumber, truncate } from "@/lib/utils";
import { celdaSaludPorPct } from "@/lib/cobertura";

import type { CompetitorsData } from "../_hooks/use-competidores-data";

function etiquetaHhi(hhi: number): string {
  if (hhi < 1500) return "Mercado competitivo";
  if (hhi < 2500) return "Concentración moderada";
  return "Mercado concentrado";
}

export function CompetidoresKpis({
  data,
  isLoading,
}: {
  data: CompetitorsData | undefined;
  isLoading: boolean;
}) {
  const ofertaUnica = celdaSaludPorPct(
    data?.pct_oferta_unica,
    data?.cobertura_ofertas_pct,
    "licitaciones con un solo ofertante",
  );

  // Tira quieta: las cifras aparecen a la vez, sin entrada escalonada. Es una
  // tira que se consulta a diario, y escalonarla animaba justo el dato que se
  // vino a leer.
  return (
    <StatStrip columns={4}>
      <StatCell label="Adjudicaciones" value={formatNumber(data?.total_adjudicaciones)} loading={isLoading} />
      <StatCell
        label="Concentración (HHI)"
        badge={<GlosarioHint termino="hhi" />}
        value={formatNumber(data?.hhi)}
        hint={data?.hhi != null ? etiquetaHhi(data.hhi) : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Oferta única"
        badge={<GlosarioHint termino="oferta_unica" />}
        value={ofertaUnica.value}
        hint={ofertaUnica.hint}
        loading={isLoading}
      />
      <StatCell
        label="Competidor principal"
        value={truncate(data?.top_competidor ?? data?.competitors?.[0]?.nombre ?? EMPTY, 30)}
        loading={isLoading}
      />
    </StatStrip>
  );
}
