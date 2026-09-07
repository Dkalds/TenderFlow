"use client";

/**
 * Los cuatro KPIs de Geografía. La concentración declara su denominador en el
 * subtítulo («del total»), que es el total de licitaciones de la misma
 * respuesta del endpoint, no de una muestra (ADR-014).
 */

import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { formatNumber, formatPercent } from "@/lib/utils";
import { DollarSign, Hash, MapPin, Trophy } from "lucide-react";

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
    <KpiStrip columns={4}>
      <KpiCard
        title="CCAA Más Activa"
        value={isLoading ? undefined : topCcaa}
        icon={Trophy}
        loading={isLoading}
      />
      <KpiCard
        title="Concentración Top 3"
        value={isLoading ? undefined : formatPercent(top3Concentration)}
        subtitle="del total"
        icon={MapPin}
        loading={isLoading}
      />
      <KpiCard
        title="Total CCAAs"
        value={isLoading ? undefined : formatNumber(totalCcaas)}
        icon={Hash}
        loading={isLoading}
      />
      <KpiCard
        title="Mayor Ticket Medio"
        value={isLoading ? undefined : ccaaMayorTicket}
        subtitle="CCAA con mayor importe/licitación"
        icon={DollarSign}
        loading={isLoading}
      />
    </KpiStrip>
  );
}
