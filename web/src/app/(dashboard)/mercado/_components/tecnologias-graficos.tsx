"use client";

/**
 * Los cinco gráficos de Tecnologías: la evolución mensual (con su conmutador
 * conteo/importe), las dos barras complementarias —volumen coloreado por
 * importe e importe coloreado por volumen— y el par donut + distribución
 * geográfica.
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle, Segmented } from "@/components/console/panel";

import type {
  BarItem,
  TecnologiaItem,
  TrendMetric,
} from "../_hooks/use-tecnologias-view";

const TecnologiasEvolutionChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasEvolutionChart })), { ssr: false, loading: () => <PanelLoading height={340} /> });
const TecnologiasVolumeBarChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasVolumeBarChart })), { ssr: false, loading: () => <PanelLoading height={420} /> });
const TecnologiasImporteBarChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasImporteBarChart })), { ssr: false, loading: () => <PanelLoading height={420} /> });
const TecnologiasDonutChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasDonutChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });
const TecnologiasGeoBarChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasGeoBarChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });

const VACIO = "Ninguna licitación del ámbito actual tiene tecnología identificada.";

const METRICAS: { value: TrendMetric; label: string }[] = [
  { value: "count", label: "Licitaciones" },
  { value: "importe", label: "Importe" },
];

export function TecnologiasEvolucion({
  data,
  techs,
  trendMetric,
  onTrendMetricChange,
  isLoading,
}: {
  data: Record<string, number | string>[];
  techs: string[];
  trendMetric: TrendMetric;
  onTrendMetricChange: (metric: TrendMetric) => void;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        title="Evolución mensual por tecnología"
        actions={
          <Segmented
            value={trendMetric}
            onChange={onTrendMetricChange}
            options={METRICAS}
            aria-label="Métrica de la evolución"
          />
        }
      />
      {isLoading ? (
        <PanelLoading height={340} />
      ) : data.length > 0 && techs.length > 0 ? (
        <TecnologiasEvolutionChart data={data} techs={techs} trendMetric={trendMetric} />
      ) : (
        <PanelEmpty title="Sin evolución" hint={VACIO} height={340} />
      )}
    </Panel>
  );
}

export function TecnologiasBarras({
  volumeBar,
  importeBar,
  isLoading,
}: {
  volumeBar: BarItem[];
  importeBar: BarItem[];
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel>
        <PanelTitle title="Licitaciones por tecnología" hint="El color indica el importe" />
        {isLoading ? (
          <PanelLoading height={420} />
        ) : volumeBar.length > 0 ? (
          <TecnologiasVolumeBarChart data={volumeBar} />
        ) : (
          <PanelEmpty title="Ninguna tecnología" hint={VACIO} height={420} />
        )}
      </Panel>

      <Panel>
        <PanelTitle title="Importe por tecnología" hint="El color indica el número de licitaciones" />
        {isLoading ? (
          <PanelLoading height={420} />
        ) : importeBar.length > 0 ? (
          <TecnologiasImporteBarChart data={importeBar} />
        ) : (
          <PanelEmpty title="Ninguna tecnología" hint={VACIO} height={420} />
        )}
      </Panel>
    </div>
  );
}

export function TecnologiasDistribucion({
  donutData,
  geoData,
  geoTechs,
  isLoading,
}: {
  donutData: TecnologiaItem[];
  geoData: Record<string, number | string>[];
  geoTechs: string[];
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel>
        <PanelTitle title="Reparto de licitaciones por tecnología" />
        {isLoading ? (
          <PanelLoading height={400} />
        ) : donutData.length > 0 ? (
          <TecnologiasDonutChart data={donutData} />
        ) : (
          <PanelEmpty title="Ninguna tecnología" hint={VACIO} height={400} />
        )}
      </Panel>

      <Panel>
        <PanelTitle title="Tecnologías por comunidad autónoma" hint="Las 10 CCAA con más licitaciones" />
        {isLoading ? (
          <PanelLoading height={400} />
        ) : geoData.length > 0 && geoTechs.length > 0 ? (
          <TecnologiasGeoBarChart data={geoData} techs={geoTechs} />
        ) : (
          <PanelEmpty title="Sin reparto geográfico" hint={VACIO} height={400} />
        )}
      </Panel>
    </div>
  );
}
