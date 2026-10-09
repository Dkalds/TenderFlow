"use client";

/**
 * UTE — con quién se alía cada competidor para ganar.
 *
 * Segunda vista del espacio Competencia (`?vista=utes`). El cuerpo vive aquí y
 * no en `(dashboard)/utes/page.tsx` por lo mismo que Competidores: `/utes`
 * redirige 308 a `/competencia?vista=utes` y los redirects de Next se resuelven
 * antes que el enrutado por ficheros, así que aquel `page.tsx` era un boundary
 * de ruta inalcanzable que además se montaba como componente, sin el contrato
 * `params`/`searchParams` que Next le pasa a una página.
 *
 * De lo general a lo concreto: el titular y la tira de cifras, la red de
 * alianzas con su lista y la evolución al lado, y al final las UTE con más
 * adjudicaciones. Aquí sólo queda ese orden: la petición y lo que el usuario
 * elige están en `_hooks/use-utes-data.ts`, las series en `_hooks/utes-series.ts`
 * y la disposición de la red en `_hooks/utes-red.ts`.
 */

import { PanelError } from "@/components/console/panel";

import { useUtesData } from "../_hooks/use-utes-data";
import { UtesAlianzas } from "./utes-alianzas";
import { UtesCabecera } from "./utes-cabecera";
import { UtesEvolucion } from "./utes-evolucion";
import { UtesKpis } from "./utes-kpis";
import { UtesMariposa } from "./utes-mariposa";
import { UtesRed } from "./utes-red";

export default function UtesView() {
  const {
    data,
    isLoading,
    error,
    refetch,
    red,
    alianzas,
    elegirEmpresa,
    mariposa,
    busqueda,
    setBusqueda,
    evolucion,
  } = useUtesData();

  if (error) {
    return <PanelError title="No se pudieron cargar las UTE" error={error} onRetry={refetch} />;
  }

  const utes = data?.top_miembros ?? [];

  return (
    <div className="space-y-4">
      <UtesCabecera kpis={data?.kpis} isLoading={isLoading} />

      <UtesKpis kpis={data?.kpis} comparativa={data?.tabla_comparativa} isLoading={isLoading} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <UtesRed red={red} isLoading={isLoading} onElegir={elegirEmpresa} />
        <div className="flex min-w-0 flex-col gap-4">
          <UtesAlianzas filas={alianzas} elegida={red.elegida} isLoading={isLoading} onElegir={elegirEmpresa} />
          <UtesEvolucion serie={evolucion} isLoading={isLoading} />
        </div>
      </div>

      <UtesMariposa
        filas={mariposa}
        total={utes.length}
        busqueda={busqueda}
        onBusquedaChange={setBusqueda}
        sugerencias={utes.map((ute) => ute.nombre)}
        isLoading={isLoading}
      />
    </div>
  );
}
