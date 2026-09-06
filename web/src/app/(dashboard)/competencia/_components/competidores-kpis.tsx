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

import { KpiCard } from "@/components/charts/kpi-card";
import { Stagger } from "@/components/motion";
import { formatNumber, truncate } from "@/lib/utils";
import { celdaSaludPorPct } from "@/lib/cobertura";
import { Hash, Target, AlertTriangle, Crown } from "lucide-react";

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

  return (
    <Stagger className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60 lg:grid-cols-4 [&_[data-slot=card]]:rounded-none [&_[data-slot=card]]:border-0 [&_[data-slot=card]]:bg-card">
      <Stagger.Item>
        <KpiCard
          title="Total Adjudicaciones"
          value={isLoading ? undefined : formatNumber(data?.total_adjudicaciones)}
          icon={Hash}
          loading={isLoading}
        />
      </Stagger.Item>
      <Stagger.Item>
        <KpiCard
          title="HHI Concentración"
          value={isLoading ? undefined : formatNumber(data?.hhi)}
          subtitle={data?.hhi != null ? etiquetaHhi(data.hhi) : undefined}
          icon={Target}
          loading={isLoading}
        />
      </Stagger.Item>
      <Stagger.Item>
        <KpiCard
          title="% Oferta Única"
          value={isLoading ? undefined : ofertaUnica.value}
          subtitle={isLoading ? undefined : ofertaUnica.hint}
          icon={AlertTriangle}
          loading={isLoading}
        />
      </Stagger.Item>
      <Stagger.Item>
        <KpiCard
          title="Top Competidor"
          value={
            isLoading
              ? undefined
              : truncate(data?.top_competidor ?? data?.competitors?.[0]?.nombre ?? "-", 30)
          }
          icon={Crown}
          loading={isLoading}
        />
      </Stagger.Item>
    </Stagger>
  );
}
