"use client";

/**
 * Los nueve cortes del análisis de competencia, como pestañas de un solo panel.
 *
 * Eran nueve tarjetas apiladas —2.400 px de gráficos— por encima de la tabla
 * que los filtra. Aquí sólo se monta el corte activo, y todos leen la misma
 * búsqueda y el mismo ámbito que la tabla.
 */

import dynamic from "next/dynamic";

import {
  Panel,
  PanelEmpty,
  PanelLoading,
  PanelTabs,
  PanelTitle,
  panelDePestana,
} from "@/components/console/panel";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { truncate } from "@/lib/utils";

import type { ScatterPoint } from "@/components/charts/competitors-charts";

import type {
  BajasModel,
  EstacionalidadPoint,
  HeatmapModel,
  PieSlice,
  PositioningPoint,
  RadarModel,
  TreemapNode,
} from "../_hooks/competidores-series";
import type { Competitor } from "../_hooks/competidores-types";
import { CompetidoresBajas } from "./competidores-bajas";
import { CompetidoresHeatmap } from "./competidores-heatmap";

const RadarChart = dynamic(() => import("@/components/charts/radar-chart").then((m) => ({ default: m.RadarChart })), {
  ssr: false,
  loading: () => <PanelLoading height={420} />,
});
const CompetitorsBarChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsBarChart })),
  { ssr: false, loading: () => <PanelLoading height={500} /> },
);
const CompetitorsPieChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsPieChart })),
  { ssr: false, loading: () => <PanelLoading height={400} /> },
);
const CompetitorsScatterChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsScatterChart })),
  { ssr: false, loading: () => <PanelLoading height={400} /> },
);
const CompetitorsTreemap = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsTreemap })),
  { ssr: false, loading: () => <PanelLoading height={400} /> },
);
const CompetitorsPositioningChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsPositioningChart })),
  { ssr: false, loading: () => <PanelLoading height={400} /> },
);
const CompetitorsEstacionalidadChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsEstacionalidadChart })),
  { ssr: false, loading: () => <PanelLoading height={300} /> },
);

export const CORTES = [
  { key: "top20" as const, label: "Ranking" },
  { key: "cuota" as const, label: "Cuota" },
  { key: "ticket" as const, label: "Importe y clientes" },
  { key: "ccaa" as const, label: "Por CCAA" },
  { key: "treemap" as const, label: "Reparto de cuota" },
  { key: "top5" as const, label: "Posicionamiento" },
  { key: "estac" as const, label: "Estacionalidad" },
  { key: "bajas" as const, label: "Bajas" },
  { key: "radar" as const, label: "Comparador" },
] as const;

export type CorteKey = (typeof CORTES)[number]["key"];

const ID_CORTES = "cortes-competencia";

const VACIO = "Ningún competidor con adjudicaciones en el ámbito actual o con esa búsqueda.";

/**
 * El contenido de un corte: su título y el gráfico, sin otra tarjeta dentro
 * del panel (el marco ya lo pone el panel de las pestañas).
 */
function Corte({
  titulo,
  hint,
  altura,
  isLoading,
  vacio,
  vacioTitulo = "Sin datos para este corte",
  vacioHint = VACIO,
  children,
}: {
  titulo: React.ReactNode;
  hint?: React.ReactNode;
  /** Alto del esqueleto y del vacío, para que el panel no salte. */
  altura: number;
  isLoading: boolean;
  vacio: boolean;
  vacioTitulo?: string;
  vacioHint?: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <PanelTitle title={titulo} hint={hint} />
      {isLoading ? (
        <PanelLoading height={altura} />
      ) : vacio ? (
        <PanelEmpty title={vacioTitulo} hint={vacioHint} height={altura} />
      ) : (
        <ChartErrorBoundary>{children}</ChartErrorBoundary>
      )}
    </>
  );
}

export interface CompetidoresCortesProps {
  corte: CorteKey;
  onCorteChange: (corte: CorteKey) => void;
  isLoading: boolean;
  barData: Competitor[];
  pieData: PieSlice[];
  /**
   * El corte «Importe y clientes» lo pinta `CompetitorsScatterChart`, que exige
   * los dos ejes (`ticket_medio`, `n_organos`). El filtro por búsqueda del hook
   * es genérico sobre `Searchable` —le basta el nombre—, pero aquí el contrato
   * ya no puede serlo: es este panel el que se compromete con el gráfico.
   */
  scatterData: ScatterPoint[];
  scatterTop5: Set<string>;
  heatmapData: HeatmapModel;
  activeCcaa: Set<string>;
  onToggleCcaa: (ccaa: string) => void;
  treemapData: TreemapNode[];
  positioningData: PositioningPoint[];
  estacionalidadData: EstacionalidadPoint[];
  bajasSorted: BajasModel;
  radarData: RadarModel | null;
}

export function CompetidoresCortes({
  corte,
  onCorteChange,
  isLoading,
  barData,
  pieData,
  scatterData,
  scatterTop5,
  heatmapData,
  activeCcaa,
  onToggleCcaa,
  treemapData,
  positioningData,
  estacionalidadData,
  bajasSorted,
  radarData,
}: CompetidoresCortesProps) {
  return (
    <Panel>
      <PanelTabs
        label="Cortes del análisis de competencia"
        value={corte}
        onChange={onCorteChange}
        tabs={[...CORTES]}
        idBase={ID_CORTES}
      />
      <div className="pt-3.5 focus-visible:outline-none" {...panelDePestana(ID_CORTES, corte)}>
        {corte === "top20" && (
          <Corte
            titulo="Los 20 competidores con más adjudicaciones"
            altura={500}
            isLoading={isLoading}
            vacio={barData.length === 0}
          >
            <CompetitorsBarChart data={barData} />
          </Corte>
        )}
        {corte === "cuota" && (
          <Corte
            titulo="Cuota de mercado por importe: 10 primeros"
            altura={400}
            isLoading={isLoading}
            vacio={pieData.length === 0}
          >
            <CompetitorsPieChart data={pieData} />
          </Corte>
        )}
        {corte === "ticket" && (
          <Corte
            titulo="Importe medio frente a dependencia de clientes"
            altura={400}
            isLoading={isLoading}
            vacio={scatterData.length === 0}
          >
            <CompetitorsScatterChart data={scatterData} top5Names={scatterTop5} />
          </Corte>
        )}
        {corte === "ccaa" && (
          <Corte
            titulo="Actividad por CCAA y empresa"
            hint="Pulsa una CCAA para filtrar"
            altura={400}
            isLoading={isLoading}
            vacio={heatmapData.empresas.length === 0}
          >
            <CompetidoresHeatmap heatmap={heatmapData} activeCcaa={activeCcaa} onToggleCcaa={onToggleCcaa} />
          </Corte>
        )}
        {corte === "treemap" && (
          <Corte
            titulo="Cuota de mercado de los 20 primeros"
            altura={400}
            isLoading={isLoading}
            vacio={treemapData.length === 0}
          >
            <CompetitorsTreemap data={treemapData} />
          </Corte>
        )}
        {corte === "top5" && (
          <Corte
            titulo="Posicionamiento competitivo"
            altura={400}
            isLoading={isLoading}
            vacio={positioningData.length === 0}
          >
            <CompetitorsPositioningChart data={positioningData} />
          </Corte>
        )}
        {corte === "estac" && (
          <Corte
            titulo="Estacionalidad del mercado"
            hint="Con la búsqueda y el ámbito actuales"
            altura={300}
            isLoading={isLoading}
            vacio={estacionalidadData.length === 0}
          >
            <CompetitorsEstacionalidadChart data={estacionalidadData} />
          </Corte>
        )}
        {corte === "bajas" &&
          (bajasSorted.rows.length > 0 ? (
            <CompetidoresBajas bajas={bajasSorted} />
          ) : (
            <PanelEmpty
              title="Sin bajas que comparar"
              hint="Ninguna empresa con 5 contratos o más tiene baja publicada en el ámbito actual."
            />
          ))}
        {corte === "radar" &&
          (radarData ? (
            <>
              <PanelTitle
                title={`Comparación: ${truncate(radarData.nameA, 25)} frente a ${truncate(radarData.nameB, 25)}`}
              />
              <RadarChart
                data={radarData.dataA}
                name={truncate(radarData.nameA, 20)}
                compareData={radarData.dataB}
                compareName={truncate(radarData.nameB, 20)}
                height={400}
                aria-label={`Comparación de ${radarData.nameA} y ${radarData.nameB}`}
              />
            </>
          ) : (
            <PanelEmpty
              title="Elige dos empresas"
              hint="Marca dos empresas en la tabla de arriba para compararlas aquí."
            />
          ))}
      </div>
    </Panel>
  );
}
