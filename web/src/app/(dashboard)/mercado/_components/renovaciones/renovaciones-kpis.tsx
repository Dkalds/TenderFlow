"use client";

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatCurrency, formatNumber } from "@/lib/utils";
import type { Renovaciones } from "../../_hooks/use-renovaciones";

/**
 * Los cuatro totales de la ventana.
 *
 * Vienen del endpoint de resumen, calculados sobre el dataset completo, y no de
 * la página de filas que alimenta la tabla: sumar aquí las 200 filas servidas
 * daría un número más pequeño y con pinta de total (ADR-014 §2). Tampoco salen
 * del cruce con tu cartera, que es una marca por fila y no un agregado.
 *
 * Mientras el resumen no ha llegado se pinta «…», no un cero: un cero es una
 * respuesta, y aquí todavía no hay ninguna.
 */
export function RenovacionesKpis({ totales }: { totales: Renovaciones["totales"] }) {
  return (
    <StatStrip columns={4} className="lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]">
      <StatCell
        label="Contratos venciendo"
        value={totales ? formatNumber(totales.contratos_venciendo) : "…"}
        hint="En toda la ventana, no sólo en la tabla"
      />
      <StatCell
        label="Importe en juego"
        value={totales ? formatCurrency(totales.importe_en_juego) : "…"}
        hint="Suma de lo adjudicado que vence"
      />
      <StatCell
        label="Importe en alto riesgo"
        value={totales ? formatCurrency(totales.importe_alto_riesgo) : "…"}
        hint="Riesgo de cambio ≥ 60%"
      />
      <StatCell
        label="Oportunidades calientes"
        value={totales ? formatNumber(totales.calientes) : "…"}
        hint="Alto riesgo y ≤ 30 días"
      />
    </StatStrip>
  );
}
