"use client";

/**
 * Los gráficos de «Proyectos y módulos»: por familia, por módulo SAP (el
 * desglose de ERP) y por tipo de proyecto. En cada bloque, barras o tarta para
 * la cantidad y un treemap para el importe.
 *
 * Los `dynamic` viven aquí y no en la vista para que el bundle de la vista no
 * arrastre recharts hasta que este bloque se monta.
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";

import type {
  FilaCategoria,
  NodoImporte,
  TipoEstadoRow,
  TipoProyectoRow,
} from "../_hooks/use-proyectos-modulos-view";

const cargando = (height: number) =>
  function Cargando() {
    return <PanelLoading height={height} />;
  };
const CategoriasBarChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then((m) => ({ default: m.CategoriasBarChart })), { ssr: false, loading: cargando(360) });
const TiposPieChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then((m) => ({ default: m.TiposPieChart })), { ssr: false, loading: cargando(400) });
const ImporteTreemap = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then((m) => ({ default: m.ImporteTreemap })), { ssr: false, loading: cargando(350) });
const TipoEstadoStackedChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then((m) => ({ default: m.TipoEstadoStackedChart })), { ssr: false, loading: cargando(360) });

export const SIN_FAMILIAS = "Ninguna licitación del ámbito actual es de una familia de la taxonomía.";
export const SIN_MODULOS = "Ninguna licitación SAP del ámbito actual menciona un módulo.";
const SIN_TIPOS = "Ninguna licitación del ámbito actual tiene tipo de proyecto identificado.";

/** Barras de cantidad y treemap de importe de un mismo corte, uno junto al otro. */
function ParCategorias({
  titulo,
  filas,
  treemap,
  vacio,
  isLoading,
}: {
  titulo: { cantidad: string; importe: string };
  filas: FilaCategoria[];
  treemap: NodoImporte[];
  vacio: string;
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel>
        <PanelTitle title={titulo.cantidad} />
        {isLoading ? (
          <PanelLoading height={360} />
        ) : filas.length > 0 ? (
          <CategoriasBarChart data={filas} />
        ) : (
          <PanelEmpty title="Sin licitaciones" hint={vacio} height={360} />
        )}
      </Panel>
      <Panel>
        <PanelTitle title={titulo.importe} />
        {isLoading ? (
          <PanelLoading height={350} />
        ) : treemap.length > 0 ? (
          <ImporteTreemap data={treemap} />
        ) : (
          <PanelEmpty title="Sin importes" hint={vacio} height={350} />
        )}
      </Panel>
    </div>
  );
}

export function GraficosFamilias(props: { filas: FilaCategoria[]; treemap: NodoImporte[]; isLoading: boolean }) {
  return (
    <ParCategorias
      titulo={{ cantidad: "Licitaciones por familia", importe: "Importe por familia" }}
      vacio={SIN_FAMILIAS}
      {...props}
    />
  );
}

export function GraficosModulos(props: { filas: FilaCategoria[]; treemap: NodoImporte[]; isLoading: boolean }) {
  return (
    <ParCategorias
      titulo={{ cantidad: "Licitaciones por módulo SAP", importe: "Importe por módulo SAP" }}
      vacio={SIN_MODULOS}
      {...props}
    />
  );
}

export function GraficosTipos({
  tiposPie,
  tiposTreemap,
  tipoEstadoData,
  tipoEstadoEstados,
  isLoading,
}: {
  tiposPie: TipoProyectoRow[];
  tiposTreemap: NodoImporte[];
  tipoEstadoData: TipoEstadoRow[];
  tipoEstadoEstados: string[];
  isLoading: boolean;
}) {
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
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

        <Panel>
          <PanelTitle title="Importe por tipo de proyecto" />
          {isLoading ? (
            <PanelLoading height={350} />
          ) : tiposTreemap.length > 0 ? (
            <ImporteTreemap data={tiposTreemap} />
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
