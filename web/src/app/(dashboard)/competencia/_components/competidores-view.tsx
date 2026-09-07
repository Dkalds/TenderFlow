"use client";

/**
 * Competidores — quién gana, con cuánta cuota y a qué baja.
 *
 * El cuerpo vive aquí y no en un `page.tsx` de ruta propia porque
 * `/competidores` no es alcanzable: `next.config.ts` la redirige con un 308
 * permanente a `/competencia?vista=competidores`, y los redirects de Next
 * corren ANTES del enrutado por sistema de ficheros. Mientras el fichero
 * estuvo en `(dashboard)/competidores/page.tsx` era a la vez boundary de ruta
 * —que nunca llegaba a ejecutarse— y componente montado por el espacio, así
 * que Next no podía tratarlo como lo primero: un `page.tsx` recibe el contrato
 * `params`/`searchParams` y este se montaba sin él. Mismo reparto que las ocho
 * vistas de Mercado y las seis de Ops.
 *
 * Lo que preserva los enlaces guardados es el 308, no el fichero de ruta. El
 * dossier de empresa (`competidores/empresa/[empresaId]`) sí sigue siendo ruta:
 * el redirect es de path exacto y no lo tapa.
 *
 * Aquí sólo queda el orden de la pantalla. Las peticiones y el estado están en
 * `_hooks/use-competidores-data.ts`, las series en `_hooks/competidores-series.ts`
 * y la lógica de la tabla en `_hooks/competidores-tabla.ts`; cada bloque
 * visible es un componente de este mismo directorio.
 */

import { startTransition, useState } from "react";

import { useCompetidoresData } from "../_hooks/use-competidores-data";
import { CompetidoresBanner } from "./competidores-banner";
import { CompetidoresCortes, type CorteKey } from "./competidores-cortes";
import { CompetidoresDossier } from "./competidores-dossier";
import { CompetidoresKpis } from "./competidores-kpis";
import { CompetidoresTabla } from "./competidores-tabla";
import { CompetidoresToolbar } from "./competidores-toolbar";

export default function CompetidoresView() {
  const {
    data,
    isLoading,
    error,
    series,
    search,
    setSearch,
    activeCcaa,
    toggleCcaa,
    sortKey,
    sortDir,
    toggleSort,
    selectedCompanies,
    onToggleCompare,
    drillDownCompany,
    setDrillDownCompany,
    drillDownCompanyId,
    drillDownGroupIds,
    drillDownProfile,
    drillDownAwards,
    isLoadingDrillDownProfile,
    isLoadingDrillDownAwards,
    watchedIds,
    toggleWatch,
  } = useCompetidoresData();

  const [corte, setCorte] = useState<CorteKey>("top20");

  if (error) {
    return (
      <div
        className="border-destructive/50 bg-destructive/10 rounded-lg border p-6 text-center"
        role="alert"
      >
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  const watched = drillDownGroupIds.some((id) => watchedIds.has(id));

  return (
    <div className="flex min-h-0 gap-4">
      <div className="min-w-0 flex-1 space-y-4">
        <CompetidoresToolbar
          search={search}
          onSearchChange={setSearch}
          suggestions={data?.competitors?.map((c) => c.nombre) ?? []}
        />

        {/* Marcador del espacio: los cuatro KPIs del mercado competitivo. */}
        <CompetidoresKpis data={data} isLoading={isLoading} />

        {/* La tabla gobierna los nueve cortes, así que va primero. Antes había
            que bajar 2.400 px de gráficos para llegar a la superficie de
            trabajo que los filtra. */}
        <CompetidoresTabla
          filas={series.filteredSorted}
          totalEmpresas={data?.total_empresas ?? data?.competitors.length ?? 0}
          isLoading={isLoading}
          search={search}
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={toggleSort}
          selectedCompanies={selectedCompanies}
          onToggleCompare={onToggleCompare}
          onDrillDown={setDrillDownCompany}
        />

        <CompetidoresBanner seleccionadas={selectedCompanies.length} />

        {/* Los nueve gráficos, como cortes con pestañas de la misma tabla. */}
        <CompetidoresCortes
          corte={corte}
          onCorteChange={setCorte}
          isLoading={isLoading}
          barData={series.barData}
          pieData={series.pieData}
          scatterData={series.scatterData}
          scatterTop5={series.scatterTop5}
          heatmapData={series.heatmapData}
          activeCcaa={activeCcaa}
          onToggleCcaa={toggleCcaa}
          treemapData={series.treemapData}
          positioningData={series.positioningData}
          estacionalidadData={series.estacionalidadData}
          bajasSorted={series.bajasSorted}
          radarData={series.radarData}
        />
      </div>

      {drillDownCompany && (
        <CompetidoresDossier
          company={drillDownCompany}
          companyId={drillDownCompanyId}
          groupIds={drillDownGroupIds}
          profile={drillDownProfile}
          recentAwards={drillDownAwards}
          isLoadingProfile={isLoadingDrillDownProfile}
          isLoadingAwards={isLoadingDrillDownAwards}
          watched={watched}
          watchPending={toggleWatch.isPending}
          onToggleWatch={() =>
            toggleWatch.mutate({ empresaIds: drillDownGroupIds, watched })
          }
          onClose={() => startTransition(() => setDrillDownCompany(null))}
        />
      )}
    </div>
  );
}
