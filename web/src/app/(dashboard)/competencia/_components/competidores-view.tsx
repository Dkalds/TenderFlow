"use client";

/**
 * Competidores — quién gana, con cuánta cuota y a qué baja.
 *
 * Primero el dibujo, después la lista: el titular de dato y las cifras del
 * mercado arriba, el reparto en una barra, el mapa de competidores junto a tus
 * vigilados, el perfil de la empresa abierta en una franja, el cara a cara y la
 * matriz por comunidad, y el ranking al final. Hasta 2026-10 era una tabla de
 * cien filas con nueve gráficos detrás de pestañas, de uno en uno.
 *
 * El cuerpo vive aquí y no en un `page.tsx` de ruta propia porque
 * `/competidores` no es alcanzable: `next.config.ts` la redirige con un 308
 * permanente a `/competencia?vista=competidores`, y los redirects de Next
 * corren antes del enrutado por sistema de ficheros. Lo que preserva los
 * enlaces guardados es el 308, no el fichero de ruta. El análisis completo de
 * una empresa sí es ruta propia, `competencia/empresa/[empresaId]`.
 *
 * Aquí solo queda el orden de la pantalla. Las peticiones y el estado están en
 * `_hooks/use-competidores-data.ts` y las series en
 * `_hooks/competidores-series.ts`; cada bloque visible es un componente de este
 * mismo directorio.
 */

import { PanelError } from "@/components/console/panel";
import { cn } from "@/lib/utils";

import { useCompetidoresData } from "../_hooks/use-competidores-data";
import { CompetidorPerfil } from "./competidor-perfil";
import { CompetidoresCabecera } from "./competidores-cabecera";
import { CompetidoresCifras } from "./competidores-cifras";
import { CompetidoresDuelo } from "./competidores-duelo";
import { CompetidoresHeatmap } from "./competidores-heatmap";
import { CompetidoresMapa } from "./competidores-mapa";
import { CompetidoresRanking } from "./competidores-ranking";
import { CompetidoresReparto } from "./competidores-reparto";
import { CompetidoresResolucion } from "./competidores-resolucion";
import { CompetidoresTruncado } from "./competidores-truncado";
import { CompetidoresVigilados } from "./competidores-vigilados";

export default function CompetidoresView() {
  const {
    data,
    isLoading,
    error,
    refetch,
    series,
    vigiladas,
    search,
    setSearch,
    metrica,
    setMetrica,
    lente,
    setLente,
    activeCcaa,
    toggleCcaa,
    sortKey,
    sortDir,
    toggleSort,
    abrirEmpresa,
    cerrarPerfil,
    compararCon,
    quitarRival,
    perfilId,
    perfilIds,
    perfil,
    perfilLoading,
    perfilError,
    refetchPerfil,
  } = useCompetidoresData();

  if (error) {
    return <PanelError title="No se pudieron cargar los competidores" error={error} onRetry={refetch} />;
  }

  const { abierta, rival, duelo } = series;
  const filtrado = Boolean(search.trim());
  const totalEmpresas = data?.total_empresas ?? null;

  return (
    <div className="space-y-4">
      <CompetidoresCabecera
        concentracion={series.concentracion}
        metrica={metrica}
        onMetricaChange={setMetrica}
        importeTotal={data?.importe_total ?? null}
        totalAdjudicaciones={data?.total_adjudicaciones ?? null}
        totalEmpresas={totalEmpresas}
        nRecibidas={data?.competitors?.length ?? 0}
        search={search}
        onSearchChange={setSearch}
        suggestions={data?.competitors?.map((c) => c.nombre) ?? []}
        isLoading={isLoading}
      />

      <CompetidoresCifras data={data} meses={series.meses} isLoading={isLoading} />

      {/* Las cuotas de esta pantalla solo son las del ámbito si la API lo
          analizó entero y el maestro tiene resueltas las empresas. Si alguna de
          las dos cosas falla, se avisa aquí, junto a las cifras que afecta. */}
      <CompetidoresTruncado truncado={data?.truncado} limite={data?.limite_filas} />
      <CompetidoresResolucion />

      <CompetidoresReparto
        tramos={series.reparto}
        metrica={metrica}
        isLoading={isLoading}
        onEmpresaClick={abrirEmpresa}
      />

      {/* `grid-cols-1`: sin él la columna implícita mide lo que pida su
          contenido, y el mapa (recharts) ensanchaba la página en el móvil. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <CompetidoresMapa
          mapa={series.mapa}
          lente={lente}
          onLenteChange={setLente}
          hayVigiladas={vigiladas.size > 0}
          filtrado={filtrado}
          isLoading={isLoading}
          onEmpresaClick={abrirEmpresa}
        />
        <CompetidoresVigilados />
      </div>

      {abierta && (
        <CompetidorPerfil
          empresa={abierta}
          rango={series.rangoAbierta}
          ordenTxt={metrica === "importe" ? "importe" : "adjudicaciones"}
          totalEmpresas={totalEmpresas}
          empresaId={perfilId}
          empresaIds={perfilIds}
          perfil={perfil}
          isLoading={perfilLoading}
          error={perfilError}
          onRetry={refetchPerfil}
          enDuelo={rival != null}
          onClose={cerrarPerfil}
        />
      )}

      <div className={cn("grid grid-cols-1 gap-4", duelo && "xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]")}>
        {abierta && rival && duelo && (
          <CompetidoresDuelo nombreA={abierta.nombre} nombreB={rival.nombre} filas={duelo} onQuitar={quitarRival} />
        )}
        <CompetidoresHeatmap
          heatmap={series.heatmap}
          activeCcaa={activeCcaa}
          onToggleCcaa={toggleCcaa}
          filtrado={filtrado}
          isLoading={isLoading}
        />
      </div>

      <CompetidoresRanking
        ordenados={series.ordenados}
        tabla={series.tabla}
        metrica={metrica}
        totalEmpresas={totalEmpresas}
        search={search}
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={toggleSort}
        abierta={abierta?.nombre ?? null}
        rival={rival?.nombre ?? null}
        vigiladas={vigiladas}
        onAbrir={abrirEmpresa}
        onComparar={compararCon}
        isLoading={isLoading}
      />
    </div>
  );
}
