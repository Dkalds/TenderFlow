"use client";

/**
 * UTEs — con quién se alía cada competidor para ganar.
 *
 * Segunda vista del espacio Competencia (`?vista=utes`). El cuerpo vive aquí y
 * no en `(dashboard)/utes/page.tsx` por lo mismo que Competidores: `/utes`
 * redirige 308 a `/competencia?vista=utes` y los redirects de Next se resuelven
 * antes que el enrutado por ficheros, así que aquel `page.tsx` era un boundary
 * de ruta inalcanzable que además se montaba como componente, sin el contrato
 * `params`/`searchParams` que Next le pasa a una página.
 *
 * Aquí sólo queda el orden de la pantalla: la petición y sus derivaciones están
 * en `_hooks/use-utes-data.ts` y `_hooks/utes-series.ts`, y cada bloque visible
 * es un componente de este mismo directorio.
 */

import { ExportPopover } from "@/components/export-popover";

import { useUtesData } from "../_hooks/use-utes-data";
import { UtesGraficosDistribucion, UtesGraficosMiembros } from "./utes-graficos";
import { UtesKpis } from "./utes-kpis";
import { UtesMiembros } from "./utes-miembros";
import { UtesComparativa, UtesSocios } from "./utes-tablas";

export default function UtesView() {
  const {
    data,
    isLoading,
    error,
    memberSearch,
    setMemberSearch,
    comparativaRows,
    filteredMiembros,
    memberDistribution,
    topMiembrosByImporte,
  } = useUtesData();

  if (error) {
    return (
      <div
        className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center"
        role="alert"
      >
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* El nombre del corte lo pone la cabecera del espacio; aquí queda la
          acción, que es lo único que no puede vivir allí. */}
      <div className="flex items-center">
        <div className="flex-1" />
        <ExportPopover
          extraParams={{ section: "utes" }}
          className="[&>button]:h-8 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs"
        />
      </div>

      <UtesKpis kpis={data?.kpis} isLoading={isLoading} />

      <UtesGraficosMiembros
        topMiembros={data?.top_miembros}
        evolucion={data?.evolucion}
        isLoading={isLoading}
      />

      <UtesSocios socios={data?.socios_frecuentes} isLoading={isLoading} />

      <UtesGraficosDistribucion
        memberDistribution={memberDistribution}
        topMiembrosByImporte={topMiembrosByImporte}
        isLoading={isLoading}
      />

      <UtesComparativa filas={comparativaRows} isLoading={isLoading} />

      <UtesMiembros
        filas={filteredMiembros}
        totalMiembros={data?.top_miembros?.length ?? 0}
        search={memberSearch}
        onSearchChange={setMemberSearch}
        isLoading={isLoading}
      />
    </div>
  );
}
