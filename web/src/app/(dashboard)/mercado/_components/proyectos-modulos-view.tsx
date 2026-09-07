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
      descripcion="Desglose por tipo de proyecto y módulo SAP."
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
    toggleModSort,
    isLoading,
    error,
  } = useProyectosModulosView();

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="sr-only">
            Proyectos &amp; Módulos
          </h1>
          <p className="text-muted-foreground">
            Desglose por tipo de proyecto y módulo SAP.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "proyectos-modulos" }}
        />
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
        onSort={toggleModSort}
      />

      <ProyectosTiposTabla tipos={tipos} isLoading={isLoading} />

      <ProyectosCpvTabla filas={data?.cpv ?? []} isLoading={isLoading} />
    </div>
  );
}
