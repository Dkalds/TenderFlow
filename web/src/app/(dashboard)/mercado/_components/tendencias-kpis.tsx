"use client";

/**
 * La tira de cinco KPIs de Tendencias: totales de la serie, las dos variaciones
 * interanuales y el mes pico que publica el backend.
 */

import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { CalendarDays, DollarSign, Hash, TrendingDown, TrendingUp } from "lucide-react";

import type { MesPico } from "../_hooks/use-tendencias-view";

export function TendenciasKpis({
  totalCount,
  totalImporte,
  yoyCount,
  yoyImporte,
  mesPico,
  isLoading,
}: {
  totalCount: number;
  totalImporte: number;
  /** `null` cuando la serie no cubre dos años completos: el YoY no es calculable. */
  yoyCount: number | null;
  yoyImporte: number | null;
  mesPico: MesPico | undefined;
  isLoading: boolean;
}) {
  return (
    <KpiStrip columns={5}>
      <KpiCard title="Total Licitaciones" value={isLoading ? undefined : formatNumber(totalCount)} icon={Hash} loading={isLoading} />
      <KpiCard title="Importe Total" value={isLoading ? undefined : formatCurrency(totalImporte)} icon={DollarSign} loading={isLoading} />
      <KpiCard
        title="Var. YoY (cantidad)"
        value={isLoading ? undefined : yoyCount != null ? formatPercent(yoyCount) : "-"}
        icon={yoyCount != null && yoyCount >= 0 ? TrendingUp : TrendingDown}
        trend={yoyCount ?? undefined}
        loading={isLoading}
      />
      <KpiCard
        title="Var. YoY (importe)"
        value={isLoading ? undefined : yoyImporte != null ? formatPercent(yoyImporte) : "-"}
        icon={yoyImporte != null && yoyImporte >= 0 ? TrendingUp : TrendingDown}
        trend={yoyImporte ?? undefined}
        loading={isLoading}
      />
      {/* Mes Pico KPI */}
      <KpiCard
        title="Mes Pico"
        value={isLoading ? undefined : mesPico ? mesPico.mes : "-"}
        subtitle={
          mesPico
            ? `${formatCurrency(mesPico.importe)} · ${formatNumber(mesPico.count)} lic.`
            : undefined
        }
        icon={CalendarDays}
        loading={isLoading}
      />
    </KpiStrip>
  );
}
