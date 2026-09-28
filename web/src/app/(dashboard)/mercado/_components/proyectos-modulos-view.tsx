"use client";

/**
 * Vista compartida por la ruta `/proyectos-modulos` y por `?vista=proyectos` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 *
 * Es una de las dos vistas `experimental` del espacio (`lib/space-views.ts`),
 * así que se monta detrás de `VistaExperimental`: la flag
 * `mercado_proyectos_modulos` puede apagarla desde Ops, y sin backend de flags
 * sigue visible y marcada.
 */

import { PanelError } from "@/components/console/panel";
import { ExportPopover } from "@/components/export-popover";

import { useProyectosModulosView } from "../_hooks/use-proyectos-modulos-view";
import { ProyectosGraficos } from "./proyectos-graficos";
import { ProyectosKpisCobertura, ProyectosKpisSap } from "./proyectos-kpis";
import {
  ProyectosCpvTabla,
  ProyectosModulosTabla,
  ProyectosTiposTabla,
} from "./proyectos-tablas";
import { VistaExperimental } from "./vista-experimental";

export default function ProyectosModulosView() {
  return (
    <VistaExperimental
      flag="mercado_proyectos_modulos"
      vista="proyectos"
      descripcion="Qué se licita en SAP: tipos de proyecto y módulos."
    >
      <ProyectosModulosContenido />
    </VistaExperimental>
  );
}

function ProyectosModulosContenido() {
  const {
    data,
    modulos,
    tipos,
    ticketS4Hana,
    modulosSorted,
    tiposPie,
    modulosTreemap,
    tiposTreemap,
    tipoEstadoEstados,
    tipoEstadoData,
    sortedModulosAvg,
    modSortKey,
    modSortDir,
    toggleModSort,
    isLoading,
    error,
    refetch,
  } = useProyectosModulosView();

  if (error) {
    return <PanelError title="No se pudieron cargar los proyectos y módulos" error={error} onRetry={refetch} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <h1 className="sr-only">Proyectos y módulos</h1>
        <ExportPopover extraParams={{ section: "proyectos-modulos" }} label="Exportar módulos" />
      </div>

      <ProyectosKpisSap data={data} ticketS4Hana={ticketS4Hana} isLoading={isLoading} />

      <ProyectosKpisCobertura
        data={data}
        nModulos={modulos.length}
        nTipos={tipos.length}
        isLoading={isLoading}
      />

      <ProyectosGraficos
        modulosSorted={modulosSorted}
        tiposPie={tiposPie}
        modulosTreemap={modulosTreemap}
        tiposTreemap={tiposTreemap}
        tipoEstadoData={tipoEstadoData}
        tipoEstadoEstados={tipoEstadoEstados}
        isLoading={isLoading}
      />

      <ProyectosModulosTabla
        filas={sortedModulosAvg}
        isLoading={isLoading}
        sortKey={modSortKey}
        sortDir={modSortDir}
        onSort={toggleModSort}
      />

      <ProyectosTiposTabla tipos={tipos} isLoading={isLoading} />

      <ProyectosCpvTabla filas={data?.cpv ?? []} isLoading={isLoading} />
    </div>
  );
}
