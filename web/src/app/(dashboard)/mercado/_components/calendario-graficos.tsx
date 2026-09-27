"use client";

/**
 * Los dos gráficos que acompañan al heatmap del Calendario: el total por mes y
 * el promedio por día de la semana.
 *
 * Los dos títulos llevan el año seleccionado porque las dos cifras dependen de
 * él: sin ese universo declarado, «media de 12 publicaciones el martes» no dice
 * de cuándo (ADR-014).
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";

import type { DowPoint, MonthlyPoint } from "../_hooks/use-calendario-view";

const CalendarioMonthlyChart = dynamic(() => import("@/components/charts/calendario-charts").then(m => ({ default: m.CalendarioMonthlyChart })), { ssr: false, loading: () => <PanelLoading height={300} /> });
const CalendarioDowChart = dynamic(() => import("@/components/charts/calendario-charts").then(m => ({ default: m.CalendarioDowChart })), { ssr: false, loading: () => <PanelLoading height={200} /> });

export function CalendarioMensual({
  data,
  selectedYear,
  etiqueta = "Publicaciones",
  isLoading,
}: {
  data: MonthlyPoint[];
  selectedYear: number;
  /** «Publicaciones» o «Cierres»: nombra la serie y el título. */
  etiqueta?: string;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title={`${etiqueta} por mes — ${selectedYear}`} />
      {isLoading ? (
        <PanelLoading height={300} />
      ) : data.length > 0 ? (
        <CalendarioMonthlyChart data={data} etiqueta={etiqueta} />
      ) : (
        <PanelEmpty
          title={`Sin ${etiqueta.toLowerCase()} en ${selectedYear}`}
          hint="Prueba con otro año o amplía el ámbito."
          height={300}
        />
      )}
    </Panel>
  );
}

export function CalendarioDiaSemana({
  data,
  selectedYear,
  isLoading,
}: {
  data: DowPoint[];
  selectedYear: number;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title={`Distribución por día de la semana — ${selectedYear}`} />
      {isLoading ? (
        <PanelLoading height={200} />
      ) : data.some((d) => d.promedio > 0) ? (
        <CalendarioDowChart data={data} />
      ) : (
        <PanelEmpty
          title={`Sin actividad en ${selectedYear}`}
          hint="No hay días con licitaciones en este año y ámbito."
          height={200}
        />
      )}
    </Panel>
  );
}
