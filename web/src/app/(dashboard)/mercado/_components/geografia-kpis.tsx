"use client";

/**
 * Los cuatro KPIs de Geografía. La concentración dice sobre qué total se mide
 * («del total de licitaciones»): el de la misma respuesta, no una muestra
 * (ADR-014).
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatNumber, formatPercent } from "@/lib/utils";

export function GeografiaKpis({
  topCcaa,
  top3Concentration,
  totalCcaas,
  ccaaMayorTicket,
  isLoading,
}: {
  topCcaa: string;
  /** % de licitaciones que acumulan las tres CCAA más activas. */
  top3Concentration: number;
  totalCcaas: number;
  ccaaMayorTicket: string;
  isLoading: boolean;
}) {
  return (
    <StatStrip columns={4}>
      <StatCell label="CCAA más activa" value={topCcaa} loading={isLoading} />
      <StatCell
        label="Concentración en las 3 primeras"
        value={formatPercent(top3Concentration)}
        hint="Del total de licitaciones"
        loading={isLoading}
      />
      <StatCell label="CCAA con licitaciones" value={formatNumber(totalCcaas)} loading={isLoading} />
      <StatCell
        label="Mayor importe medio"
        value={ccaaMayorTicket}
        hint="CCAA con más importe por licitación"
        loading={isLoading}
      />
    </StatStrip>
  );
}
