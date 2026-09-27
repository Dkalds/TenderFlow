"use client";

/**
 * Los cinco KPIs de UTEs: volumen, importe, los dos tickets medios que se
 * comparan entre sí y cuántas empresas distintas participan.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatCurrency, formatNumber } from "@/lib/utils";

import type { UTEsKpis } from "../_hooks/utes-types";

export function UtesKpis({
  kpis,
  isLoading,
}: {
  kpis: UTEsKpis | undefined;
  isLoading: boolean;
}) {
  return (
    <StatStrip columns={5}>
      <StatCell label="UTE" value={formatNumber(kpis?.total_ute)} loading={isLoading} />
      <StatCell label="Importe en UTE" value={formatCurrency(kpis?.importe_ute)} loading={isLoading} />
      <StatCell label="Importe medio en UTE" value={formatCurrency(kpis?.ticket_medio_ute)} loading={isLoading} />
      <StatCell
        label="Importe medio en solitario"
        value={formatCurrency(kpis?.ticket_medio_individual)}
        loading={isLoading}
      />
      <StatCell label="Empresas distintas" value={formatNumber(kpis?.empresas_distintas)} loading={isLoading} />
    </StatStrip>
  );
}
