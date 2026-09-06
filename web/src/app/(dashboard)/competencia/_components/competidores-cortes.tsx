"use client";

/**
 * Los nueve cortes del análisis de competencia, como pestañas de un solo panel.
 *
 * Eran nueve tarjetas apiladas —2.400 px de gráficos— por encima de la tabla
 * que los filtra. Aquí sólo se monta el corte activo, y todos leen la misma
 * búsqueda y el mismo ámbito que la tabla.
 */

import dynamic from "next/dynamic";

import { EmptyState } from "@/components/ui/empty-state";
import { Panel, PanelTabs } from "@/components/console/panel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { truncate } from "@/lib/utils";
import { Users } from "lucide-react";

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
  loading: () => <Skeleton className="h-[420px] w-full rounded-md" />,
});
const CompetitorsBarChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsBarChart })),
  { ssr: false, loading: () => <Skeleton className="h-[500px] w-full rounded-md" /> },
);
const CompetitorsPieChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsPieChart })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsScatterChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsScatterChart })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsTreemap = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsTreemap })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsPositioningChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsPositioningChart })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsEstacionalidadChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsEstacionalidadChart })),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-md" /> },
);

export const CORTES = [
  { key: "top20" as const, label: "Top 20" },
  { key: "cuota" as const, label: "Cuota" },
  { key: "ticket" as const, label: "Ticket vs cliente" },
  { key: "ccaa" as const, label: "Actividad CCAA" },
  { key: "treemap" as const, label: "Treemap" },
  { key: "top5" as const, label: "Top 5 métricas" },
  { key: "estac" as const, label: "Estacionalidad" },
  { key: "bajas" as const, label: "Bajas" },
  { key: "radar" as const, label: "Comparador" },
] as const;

export type CorteKey = (typeof CORTES)[number]["key"];

/** Tarjeta con título: la envoltura común de siete de los nueve cortes. */
function CorteCard({
  titulo,
  hint,
  altura,
  isLoading,
  vacio,
  children,
}: {
  titulo: React.ReactNode;
  hint?: string;
  /** Alto del esqueleto mientras carga, para que el panel no salte. */
  altura: string;
  isLoading: boolean;
  vacio: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{titulo}</CardTitle>
        {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className={`${altura} w-full`} />
        ) : vacio ? (
          <EmptyState />
        ) : (
          <ChartErrorBoundary>{children}</ChartErrorBoundary>
        )}
      </CardContent>
    </Card>
  );
}

export interface CompetidoresCortesProps {
  corte: CorteKey;
  onCorteChange: (corte: CorteKey) => void;
  isLoading: boolean;
  barData: Competitor[];
  pieData: PieSlice[];
  /**
   * El corte «Ticket vs cliente» lo pinta `CompetitorsScatterChart`, que exige
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
      />
      <div className="pt-3.5">
        {corte === "top20" && (
          <CorteCard
            titulo="Top 20 Competidores (por adjudicaciones)"
            altura="h-[500px]"
            isLoading={isLoading}
            vacio={barData.length === 0}
          >
            <CompetitorsBarChart data={barData} />
          </CorteCard>
        )}
        {corte === "cuota" && (
          <CorteCard
            titulo="Cuota de Mercado por Importe (Top 10)"
            altura="h-[400px]"
            isLoading={isLoading}
            vacio={pieData.length === 0}
          >
            <CompetitorsPieChart data={pieData} />
          </CorteCard>
        )}
        {corte === "ticket" && (
          <CorteCard
            titulo="Ticket Medio vs Dependencia de Clientes"
            altura="h-[400px]"
            isLoading={isLoading}
            vacio={scatterData.length === 0}
          >
            <CompetitorsScatterChart data={scatterData} top5Names={scatterTop5} />
          </CorteCard>
        )}
        {corte === "ccaa" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Actividad por CCAA y Empresa</CardTitle>
              <p className="text-muted-foreground text-xs">Clic en una CCAA para filtrar</p>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <Skeleton className="h-[400px] w-full" />
              ) : heatmapData.empresas.length > 0 ? (
                <CompetidoresHeatmap
                  heatmap={heatmapData}
                  activeCcaa={activeCcaa}
                  onToggleCcaa={onToggleCcaa}
                />
              ) : (
                <EmptyState />
              )}
            </CardContent>
          </Card>
        )}
        {corte === "treemap" && (
          <CorteCard
            titulo="Cuota de Mercado (Treemap Top 20)"
            altura="h-[400px]"
            isLoading={isLoading}
            vacio={treemapData.length === 0}
          >
            <CompetitorsTreemap data={treemapData} />
          </CorteCard>
        )}
        {corte === "top5" && (
          <CorteCard
            titulo="Posicionamiento Competitivo"
            altura="h-[400px]"
            isLoading={isLoading}
            vacio={positioningData.length === 0}
          >
            <CompetitorsPositioningChart data={positioningData} />
          </CorteCard>
        )}
        {corte === "estac" && estacionalidadData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Estacionalidad del mercado (filtrado)</CardTitle>
            </CardHeader>
            <CardContent>
              <ChartErrorBoundary>
                <CompetitorsEstacionalidadChart data={estacionalidadData} />
              </ChartErrorBoundary>
            </CardContent>
          </Card>
        )}
        {corte === "bajas" && bajasSorted.rows.length > 0 && (
          <CompetidoresBajas bajas={bajasSorted} />
        )}
        {corte === "radar" && radarData && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Users className="h-4 w-4" />
                Comparacion: {truncate(radarData.nameA, 25)} vs {truncate(radarData.nameB, 25)}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <RadarChart
                data={radarData.dataA}
                name={truncate(radarData.nameA, 20)}
                compareData={radarData.dataB}
                compareName={truncate(radarData.nameB, 20)}
                height={400}
              />
            </CardContent>
          </Card>
        )}
      </div>
    </Panel>
  );
}
