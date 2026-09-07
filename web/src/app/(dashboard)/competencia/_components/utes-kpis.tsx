"use client";

/**
 * Los cinco KPIs de UTEs: volumen, importe, los dos tickets medios que se
 * comparan entre sí y cuántas empresas distintas participan.
 */

import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { Handshake, TrendingUp, Users } from "lucide-react";

import type { UTEsKpis } from "../_hooks/utes-types";

export function UtesKpis({
  kpis,
  isLoading,
}: {
  kpis: UTEsKpis | undefined;
  isLoading: boolean;
}) {
  return (
    <KpiStrip columns={5}>
      <KpiCard
        title="Total UTEs"
        value={isLoading ? undefined : formatNumber(kpis?.total_ute)}
        icon={Handshake}
        loading={isLoading}
      />
      <KpiCard
        title="Importe UTEs"
        value={isLoading ? undefined : formatCurrency(kpis?.importe_ute)}
        icon={TrendingUp}
        loading={isLoading}
      />
      <KpiCard
        title="Ticket Medio UTE"
        value={isLoading ? undefined : formatCurrency(kpis?.ticket_medio_ute)}
        loading={isLoading}
      />
      <KpiCard
        title="Ticket Medio Individual"
        value={isLoading ? undefined : formatCurrency(kpis?.ticket_medio_individual)}
        loading={isLoading}
      />
      <KpiCard
        title="Empresas Distintas"
        value={isLoading ? undefined : formatNumber(kpis?.empresas_distintas)}
        icon={Users}
        loading={isLoading}
      />
    </KpiStrip>
  );
}
