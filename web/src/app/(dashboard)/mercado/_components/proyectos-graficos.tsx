"use client";

/**
 * Los cinco gráficos de «Proyectos y módulos»: barras y tarta (cantidad),
 * los dos treemaps (importe) y el apilado tipo × estado.
 *
 * Los `dynamic` viven aquí y no en la vista para que el bundle de la vista no
 * arrastre recharts hasta que este bloque se monta.
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";

import type { Schemas } from "@/lib/api-types";

import type { TipoEstadoRow, TipoProyectoRow } from "../_hooks/use-proyectos-modulos-view";

const ModulosBarChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.ModulosBarChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });
const TiposPieChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TiposPieChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });
const ModulosTreemap = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.ModulosTreemap })), { ssr: false, loading: () => <PanelLoading height={350} /> });
const TiposTreemap = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TiposTreemap })), { ssr: false, loading: () => <PanelLoading height={350} /> });
const TipoEstadoStackedChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TipoEstadoStackedChart })), { ssr: false, loading: () => <PanelLoading height={360} /> });

/**
 * Nodo de treemap. La firma de índice la exige `recharts` (su `Treemap` acepta
 * datos con campos extra); sin ella el tipo no encaja con el del gráfico.
 */
export interface TreemapEntry {
  name: string;
  size: number;
  [key: string]: string | number;
}

const SIN_MODULOS = "Ninguna licitación del ámbito actual menciona un módulo SAP.";
const SIN_TIPOS = "Ninguna licitación del ámbito actual tiene tipo de proyecto identificado.";

export function ProyectosGraficos({
  modulosSorted,
  tiposPie,
  modulosTreemap,
  tiposTreemap,
  tipoEstadoData,
  tipoEstadoEstados,
  isLoading,
}: {
  modulosSorted: Schemas["ModuloEntry"][];
  tiposPie: TipoProyectoRow[];
  modulosTreemap: TreemapEntry[];
  tiposTreemap: TreemapEntry[];
  tipoEstadoData: TipoEstadoRow[];
  tipoEstadoEstados: string[];
  isLoading: boolean;
}) {
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelTitle title="Licitaciones por módulo SAP" />
          {isLoading ? (
            <PanelLoading height={400} />
          ) : modulosSorted.length > 0 ? (
            <ModulosBarChart data={modulosSorted} />
          ) : (
            <PanelEmpty title="Ningún módulo" hint={SIN_MODULOS} height={400} />
          )}
        </Panel>

        <Panel>
          <PanelTitle title="Reparto por tipo de proyecto" />
          {isLoading ? (
            <PanelLoading height={400} />
          ) : tiposPie.length > 0 ? (
            <TiposPieChart data={tiposPie} />
          ) : (
            <PanelEmpty title="Ningún tipo de proyecto" hint={SIN_TIPOS} height={400} />
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelTitle title="Importe por módulo" />
          {isLoading ? (
            <PanelLoading height={350} />
          ) : modulosTreemap.length > 0 ? (
            <ModulosTreemap data={modulosTreemap} />
          ) : (
            <PanelEmpty title="Sin importes" hint={SIN_MODULOS} height={350} />
          )}
        </Panel>

        <Panel>
          <PanelTitle title="Importe por tipo de proyecto" />
          {isLoading ? (
            <PanelLoading height={350} />
          ) : tiposTreemap.length > 0 ? (
            <TiposTreemap data={tiposTreemap} />
          ) : (
            <PanelEmpty title="Sin importes" hint={SIN_TIPOS} height={350} />
          )}
        </Panel>
      </div>

      <Panel>
        <PanelTitle title="Tipo de proyecto por estado" />
        {isLoading ? (
          <PanelLoading height={360} />
        ) : tipoEstadoData.length > 0 ? (
          <TipoEstadoStackedChart data={tipoEstadoData} estados={tipoEstadoEstados} />
        ) : (
          <PanelEmpty title="Ningún tipo de proyecto" hint={SIN_TIPOS} height={360} />
        )}
      </Panel>
    </>
  );
}
