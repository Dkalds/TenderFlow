"use client";

/**
 * El par de gráficos de Geografía: barras por cantidad y donut por importe.
 * Los dos son también controles de filtro — un clic marca esa CCAA en el ámbito
 * global, igual que la tabla y el mapa.
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";

import type { GeoItem } from "../_hooks/use-geografia-view";

const GeografiaBarChart = dynamic(() => import("@/components/charts/geografia-charts").then(m => ({ default: m.GeografiaBarChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });
const GeografiaPieChart = dynamic(() => import("@/components/charts/geografia-charts").then(m => ({ default: m.GeografiaPieChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });

export function GeografiaGraficos({
  barData,
  pieData,
  onSelect,
  isLoading,
}: {
  barData: GeoItem[];
  /** Las 9 primeras por importe más el grupo «Otros» cuando hay más de diez CCAA. */
  pieData: GeoItem[];
  onSelect: (ccaa: string) => void;
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel>
        <PanelTitle title="CCAA por número de licitaciones" hint="Pulsa una para filtrar" />
        {isLoading ? (
          <PanelLoading height={400} />
        ) : barData.length > 0 ? (
          <GeografiaBarChart data={barData} onSelect={onSelect} />
        ) : (
          <PanelEmpty
            title="Ninguna CCAA"
            hint="No hay licitaciones con comunidad autónoma en el ámbito actual."
            height={400}
          />
        )}
      </Panel>

      <Panel>
        <PanelTitle title="Reparto del importe por CCAA" hint="Pulsa una para filtrar" />
        {isLoading ? (
          <PanelLoading height={400} />
        ) : pieData.length > 0 ? (
          <GeografiaPieChart data={pieData} onSelect={onSelect} />
        ) : (
          <PanelEmpty
            title="Sin importes"
            hint="Ninguna licitación del ámbito actual trae importe."
            height={400}
          />
        )}
      </Panel>
    </div>
  );
}
