"use client";

import { CalendarClock, Euro, Flame, TrendingUp } from "lucide-react";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { formatCurrency, formatNumber } from "@/lib/utils";
import type { Horizonte } from "../../_hooks/use-horizonte";

/**
 * Los cuatro totales de la ventana.
 *
 * Vienen del endpoint de resumen, calculados sobre el dataset completo, y no de
 * la página de filas que alimenta la tabla: sumar aquí las 200 filas servidas
 * daría un número más pequeño y con pinta de total (ADR-014 §2). Mientras el
 * resumen no ha llegado se pinta «…», no un cero.
 */
export function HorizonteKpis({ totales }: { totales: Horizonte["totales"] }) {
  return (
    <KpiStrip columns={4}>
      <KpiCard
        title="Contratos venciendo"
        value={totales ? formatNumber(totales.contratos_venciendo) : "…"}
        icon={CalendarClock}
      />
      <KpiCard
        title="Importe en juego"
        value={totales ? formatCurrency(totales.importe_en_juego) : "…"}
        icon={Euro}
      />
      <KpiCard
        title="Importe en alto riesgo"
        subtitle="Riesgo de cambio ≥ 60%"
        value={totales ? formatCurrency(totales.importe_alto_riesgo) : "…"}
        icon={TrendingUp}
      />
      <KpiCard
        title="Oportunidades calientes"
        subtitle="Alto riesgo y ≤ 30 días"
        value={totales ? formatNumber(totales.calientes) : "…"}
        icon={Flame}
      />
    </KpiStrip>
  );
}
