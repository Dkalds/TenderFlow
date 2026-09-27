"use client";

/**
 * Franja de compromisos y aviso de recorte.
 *
 * Los cuatro KPI vienen calculados por la API sobre el scope pedido, y cada uno
 * mide **un reloj distinto**: el plazo externo de presentación, la acción
 * interna que vence hoy, la decisión sin tomar y la oportunidad sin siguiente
 * paso. Sumarlos daría un número que no dice a quién le toca hacer qué, así que
 * van en cuatro celdas y no en un total (ver `PipelineAgendaKpis`).
 *
 * El aviso existe porque unos KPI que describen una lista recortada no son
 * totales, y decirlo es la mitad del invariante (ADR-014).
 */

import { EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { Aviso, StatCell, StatStrip } from "@/components/console/panel";
import type { PipelineAgenda } from "@/hooks/use-pursuits";

/** Qué se quedó fuera de la lista, en el orden en que la API la recorta. */
function recortes(data: PipelineAgenda): string[] {
  const partes: string[] = [];
  if (data.pursuits_truncados) partes.push("hay más oportunidades que las listadas");
  if (data.tareas_truncadas) partes.push("hay más tareas que las listadas");
  if (data.senales_truncadas) partes.push("hay más señales que las listadas");
  return partes;
}

export function AgendaKpis({
  data,
  isLoading,
}: {
  data: PipelineAgenda | undefined;
  isLoading: boolean;
}) {
  const kpis = data?.kpis;
  const recortada = data ? recortes(data) : [];

  return (
    <>
      <StatStrip columns={4}>
        <StatCell
          label="Plazos de presentación ≤ 7 días"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.vence_semana) : EMPTY}
          tono={kpis && kpis.vence_semana > 0 ? "destructive" : undefined}
          hint={
            kpis && kpis.vence_semana > 0
              ? `${formatCompactCurrency(kpis.vence_semana_importe_eur)} en juego (incluye vencidas)`
              : "Oportunidades abiertas con plazo esta semana"
          }
        />
        <StatCell
          label="Acciones hoy o vencidas"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.acciones_hoy) : EMPTY}
          hint="Tareas propias con fecha pasada o de hoy"
        />
        <StatCell
          label="Go/No-Go pendientes"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.go_no_go_pendientes) : EMPTY}
          hint="Sin decisión tomada"
        />
        <StatCell
          label="Sin próxima acción"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.sin_proxima_accion) : EMPTY}
          tono={kpis && kpis.sin_proxima_accion > 0 ? "warning" : undefined}
          hint="Oportunidades sin tarea abierta ni siguiente paso"
        />
      </StatStrip>

      {recortada.length > 0 && (
        <Aviso tone="warning">
          Agenda parcial: {recortada.join(", ")}. Las cifras de arriba cuentan solo lo listado.
        </Aviso>
      )}
    </>
  );
}
