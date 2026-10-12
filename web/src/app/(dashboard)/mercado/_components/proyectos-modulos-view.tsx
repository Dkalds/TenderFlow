"use client";

/**
 * Vista compartida por la ruta `/proyectos-modulos` y por `?vista=proyectos` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 *
 * Qué se licita, por **familia tecnológica** (ERP, CRM, cloud,
 * ciberseguridad… las categorías de `config/keywords.py`), y dentro de ERP el
 * desglose por módulo SAP. Hasta 2026-10 solo entendía módulos SAP, sobre un
 * corpus que ya clasificaba todas esas familias. Abajo, los tipos de proyecto y
 * los CPV del ámbito, que no dependen de la familia.
 *
 * Es una de las dos vistas `experimental` del espacio (`lib/space-views.ts`),
 * así que se monta detrás de `VistaExperimental`: la flag
 * `mercado_proyectos_modulos` puede apagarla desde Ops, y sin backend de flags
 * sigue visible y marcada.
 */

import { useId } from "react";

import { PanelError } from "@/components/console/panel";
import { ExportPopover } from "@/components/export-popover";

import { useProyectosModulosView } from "../_hooks/use-proyectos-modulos-view";
import { GraficosFamilias, GraficosModulos, GraficosTipos, SIN_FAMILIAS, SIN_MODULOS } from "./proyectos-graficos";
import { ProyectosKpisFamilias, ProyectosKpisSap } from "./proyectos-kpis";
import { ProyectosCpvTabla, ProyectosTiposTabla, TablaCategorias } from "./proyectos-tablas";
import { VistaExperimental } from "./vista-experimental";

export default function ProyectosModulosView() {
  return (
    <VistaExperimental
      flag="mercado_proyectos_modulos"
      vista="proyectos"
      descripcion="Qué se licita por familia tecnológica, con los módulos SAP como desglose de ERP."
    >
      <ProyectosModulosContenido />
    </VistaExperimental>
  );
}

/** «A, B y C»: la lista en castellano. */
function enumerar(nombres: string[]): string {
  if (nombres.length <= 1) return nombres.join("");
  return `${nombres.slice(0, -1).join(", ")} y ${nombres.at(-1)}`;
}

/** Título de bloque: rótulo de sección de la vista, no de panel. */
function Seccion({ id, titulo, children }: { id: string; titulo: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-4">
      <h2 id={id} className="text-tf-body font-semibold">
        {titulo}
      </h2>
      {children}
    </section>
  );
}

function ProyectosModulosContenido() {
  const v = useProyectosModulosView();
  const idFamilias = useId();
  const idErp = useId();
  const idTipos = useId();

  if (v.error) {
    return <PanelError title="No se pudieron cargar los proyectos y módulos" error={v.error} onRetry={v.refetch} />;
  }

  const sinFamilia = v.data?.fabricantes_sin_familia ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-end">
        <h1 className="sr-only">Proyectos y módulos</h1>
        <ExportPopover extraParams={{ section: "proyectos-modulos" }} label="Exportar licitaciones" />
      </div>

      <Seccion id={idFamilias} titulo="Por familia tecnológica">
        <ProyectosKpisFamilias data={v.data} isLoading={v.isLoading} />
        <GraficosFamilias filas={v.familias} treemap={v.familiasTreemap} isLoading={v.isLoading} />
        <TablaCategorias
          titulo="Importe medio por familia"
          etiqueta="Familias"
          columnaNombre="Familia"
          filas={v.familias}
          vacio={SIN_FAMILIAS}
          isLoading={v.isLoading}
        />
        {sinFamilia.length > 0 && (
          // Lo que no suma se dice: una familia «ERP» sin Oracle no es una
          // familia «ERP» incompleta por descuido.
          <p className="text-tf-meta text-muted-foreground">
            {enumerar(sinFamilia)} no cuentan en ninguna familia: venden en varias, y repartirlas sería adivinar.
          </p>
        )}
      </Seccion>

      <Seccion id={idErp} titulo="ERP por dentro: módulos SAP">
        <ProyectosKpisSap data={v.data} ticketS4Hana={v.ticketS4Hana} isLoading={v.isLoading} />
        <GraficosModulos filas={v.modulos} treemap={v.modulosTreemap} isLoading={v.isLoading} />
        <TablaCategorias
          titulo="Importe medio por módulo SAP"
          etiqueta="Módulos SAP"
          columnaNombre="Módulo"
          filas={v.modulos}
          vacio={SIN_MODULOS}
          isLoading={v.isLoading}
        />
      </Seccion>

      <Seccion id={idTipos} titulo="Por tipo de proyecto y CPV">
        <GraficosTipos
          tiposPie={v.tiposPie}
          tiposTreemap={v.tiposTreemap}
          tipoEstadoData={v.tipoEstadoData}
          tipoEstadoEstados={v.tipoEstadoEstados}
          isLoading={v.isLoading}
        />
        <ProyectosTiposTabla tipos={v.tipos} isLoading={v.isLoading} />
        <ProyectosCpvTabla filas={v.data?.cpv ?? []} isLoading={v.isLoading} />
      </Seccion>
    </div>
  );
}
