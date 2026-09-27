"use client";

/**
 * La tira de cinco KPIs de Tendencias: totales de la serie, las dos variaciones
 * interanuales y el mes pico que publica el backend.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { EMPTY, formatCurrency, formatMonth, formatNumber, formatPercent } from "@/lib/utils";

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
    <StatStrip columns={5}>
      <StatCell label="Licitaciones" value={formatNumber(totalCount)} loading={isLoading} />
      <StatCell label="Importe total" value={formatCurrency(totalImporte)} loading={isLoading} />
      <StatCell
        label="Variación interanual (licitaciones)"
        value={yoyCount != null ? `${yoyCount >= 0 ? "+" : ""}${formatPercent(yoyCount)}` : EMPTY}
        tono={yoyCount == null ? undefined : yoyCount >= 0 ? "success" : "destructive"}
        hint={yoyCount == null ? "Hacen falta dos años completos" : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Variación interanual (importe)"
        value={yoyImporte != null ? `${yoyImporte >= 0 ? "+" : ""}${formatPercent(yoyImporte)}` : EMPTY}
        tono={yoyImporte == null ? undefined : yoyImporte >= 0 ? "success" : "destructive"}
        hint={yoyImporte == null ? "Hacen falta dos años completos" : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Mes con más importe"
        value={mesPico ? formatMonth(mesPico.mes, true) : EMPTY}
        hint={
          mesPico
            ? `${formatCurrency(mesPico.importe)} · ${formatNumber(mesPico.count)} licitaciones`
            : undefined
        }
        loading={isLoading}
      />
    </StatStrip>
  );
}
