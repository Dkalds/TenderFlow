"use client";

/**
 * Franja de compromisos y aviso de recorte.
 *
 * Los cuatro KPI vienen calculados en backend sobre el scope pedido; el aviso
 * existe porque unos KPI que describen una lista recortada no son totales, y
 * decirlo es la mitad del invariante (ADR-014).
 */

import { EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { StatCell, StatStrip } from "@/components/console/panel";
import type { PipelineAgenda } from "@/hooks/use-pursuits";

export function AgendaKpis({
  data,
  isLoading,
}: {
  data: PipelineAgenda | undefined;
  isLoading: boolean;
}) {
  const kpis = data?.kpis;

  return (
    <>
      <StatStrip columns={4} className="lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]">
        <StatCell
          label="Vence en ≤7 días"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.vence_semana) : EMPTY}
          hint={
            kpis && kpis.vence_semana > 0
              ? `${formatCompactCurrency(kpis.vence_semana_importe_eur)} en juego (incluye vencidas)`
              : "Pursuits abiertos con plazo esta semana"
          }
        />
        <StatCell
          label="Go/No-go pendientes"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.go_no_go_pendientes) : EMPTY}
          hint="Sin decisión tomada"
        />
        <StatCell
          label="Sin próxima acción"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.sin_proxima_accion) : EMPTY}
          accent={kpis && kpis.sin_proxima_accion > 0 ? "hsl(var(--warning))" : undefined}
          hint="Pursuits sin siguiente paso definido"
        />
        <StatCell
          label="Señales nuevas"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.senales_nuevas) : EMPTY}
          hint="Matches de tus reglas sin triar"
        />
      </StatStrip>

      {(data?.pursuits_truncados || data?.senales_truncadas) && (
        <p
          role="status"
          className="rounded-lg border border-amber-500/25 bg-amber-500/8 px-3 py-1.5 text-[11.5px] text-amber-700 dark:text-amber-300"
        >
          La agenda está recortada
          {data.pursuits_truncados ? " (pursuits por encima del tope interno)" : ""}
          {data.senales_truncadas ? " (hay más señales que las mostradas)" : ""} — los KPIs
          describen solo lo listado.
        </p>
      )}
    </>
  );
}
