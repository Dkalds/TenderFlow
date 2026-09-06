"use client";

/**
 * Los cinco gráficos de «Proyectos y módulos»: barras y tarta (cantidad),
 * los dos treemaps (importe) y el apilado tipo × estado.
 *
 * Los `dynamic` viven aquí y no en la vista para que el bundle de la vista no
 * arrastre recharts hasta que este bloque se monta.
 */

import dynamic from "next/dynamic";

import { EmptyState } from "@/components/ui/empty-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { FolderKanban } from "lucide-react";

import type { Schemas } from "@/lib/api-types";

import type { TipoEstadoRow, TipoProyectoRow } from "../_hooks/use-proyectos-modulos-view";

const ModulosBarChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.ModulosBarChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const TiposPieChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TiposPieChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const ModulosTreemap = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.ModulosTreemap })), { ssr: false, loading: () => <Skeleton className="h-[350px] w-full rounded-md" /> });
const TiposTreemap = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TiposTreemap })), { ssr: false, loading: () => <Skeleton className="h-[350px] w-full rounded-md" /> });
const TipoEstadoStackedChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TipoEstadoStackedChart })), { ssr: false, loading: () => <Skeleton className="h-[360px] w-full rounded-md" /> });

/**
 * Nodo de treemap. La firma de índice la exige `recharts` (su `Treemap` acepta
 * datos con campos extra); sin ella el tipo no encaja con el del gráfico.
 */
export interface TreemapEntry {
  name: string;
  size: number;
  [key: string]: string | number;
}

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
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Bar Chart: SAP Modules */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FolderKanban className="h-4 w-4" />
              Módulos SAP por Cantidad
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : modulosSorted.length > 0 ? (
              <ModulosBarChart data={modulosSorted} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Pie Chart: Project Types */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tipos de Proyecto</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : tiposPie.length > 0 ? (
              <TiposPieChart data={tiposPie} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Treemaps: Modulos + Tipos side by side */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Módulos por Importe (Treemap)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[350px] w-full" />
            ) : modulosTreemap.length > 0 ? (
              <ModulosTreemap data={modulosTreemap} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Tipos Proyecto por Importe (Treemap)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[350px] w-full" />
            ) : tiposTreemap.length > 0 ? (
              <TiposTreemap data={tiposTreemap} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Tipo de proyecto x Estado (stacked) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tipo de proyecto x Estado</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[360px] w-full" />
          ) : tipoEstadoData.length > 0 ? (
            <TipoEstadoStackedChart data={tipoEstadoData} estados={tipoEstadoEstados} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </>
  );
}
