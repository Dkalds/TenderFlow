"use client";

/**
 * El coropleto de España, con el conmutador licitaciones/importe.
 *
 * `SpainMap` monta Leaflet, que toca `window` al construir el mapa y carga su
 * CSS como side-effect: por eso entra por `next/dynamic` con `ssr: false` y con
 * un skeleton del mismo alto, para que el layout no salte al hidratar.
 */

import dynamic from "next/dynamic";

import { Panel, PanelLoading, PanelTitle, Segmented } from "@/components/console/panel";

import type { MapMetric } from "../_hooks/use-geografia-view";

const SpainMap = dynamic(() => import("@/components/charts/spain-map").then(m => ({ default: m.SpainMap })), { ssr: false, loading: () => <PanelLoading height={480} /> });

const METRICAS: { value: MapMetric; label: string }[] = [
  { value: "count", label: "Licitaciones" },
  { value: "importe", label: "Importe" },
];

export function GeografiaMapa({
  data,
  metric,
  onMetricChange,
  onCcaaClick,
  isLoading,
}: {
  data: { ccaa: string; value: number }[];
  metric: MapMetric;
  onMetricChange: (metric: MapMetric) => void;
  onCcaaClick: (ccaa: string) => void;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        title={metric === "count" ? "Licitaciones por comunidad autónoma" : "Importe por comunidad autónoma"}
        actions={
          <Segmented value={metric} onChange={onMetricChange} options={METRICAS} aria-label="Métrica del mapa" />
        }
      />
      {isLoading ? (
        <PanelLoading height={480} />
      ) : (
        <SpainMap
          data={data}
          metric={metric === "count" ? "Licitaciones" : "Importe (€)"}
          height={480}
          onCcaaClick={onCcaaClick}
        />
      )}
    </Panel>
  );
}
