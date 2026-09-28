"use client";

/**
 * Vista compartida por la ruta `/tecnologias` y por `?vista=tecnologias` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 */

import { PanelError } from "@/components/console/panel";
import { ExportPopover } from "@/components/export-popover";

import { useTecnologiasView } from "../_hooks/use-tecnologias-view";
import {
  TecnologiasBarras,
  TecnologiasDistribucion,
  TecnologiasEvolucion,
} from "./tecnologias-graficos";
import { TecnologiasCobertura, TecnologiasKpis } from "./tecnologias-kpis";
import { TecnologiasDetalle } from "./tecnologias-detalle";
import { TecnologiasHeatmap } from "./tecnologias-heatmap";
import { TecnologiasTabla, TecnologiasTopScore } from "./tecnologias-tablas";

export default function TecnologiasView() {
  const {
    data,
    items,
    filteredItems,
    donutData,
    volumeBar,
    importeBar,
    evolData,
    evolTechs,
    heatmap,
    geoData,
    geoTechs,
    detalle,
    detalleLoading,
    detalleError,
    refetchDetalle,
    scoredItems,
    filter,
    setFilter,
    selectedTech,
    setSelectedTech,
    trendMetric,
    setTrendMetric,
    isLoading,
    error,
    refetch,
  } = useTecnologiasView();

  if (error) {
    return <PanelError title="No se pudieron cargar las tecnologías" error={error} onRetry={refetch} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="sr-only">Tecnologías</h1>
          <p className="text-tf-meta text-muted-foreground">
            Qué tecnologías se licitan, cómo evolucionan y dónde.
          </p>
        </div>
        <ExportPopover extraParams={{ section: "tecnologias" }} label="Exportar tecnologías" />
      </div>

      <TecnologiasKpis data={data} isLoading={isLoading} />

      <TecnologiasCobertura data={data} isLoading={isLoading} />

      <TecnologiasEvolucion
        data={evolData}
        techs={evolTechs}
        trendMetric={trendMetric}
        onTrendMetricChange={setTrendMetric}
        isLoading={isLoading}
      />

      <TecnologiasBarras volumeBar={volumeBar} importeBar={importeBar} isLoading={isLoading} />

      <TecnologiasDistribucion
        donutData={donutData}
        geoData={geoData}
        geoTechs={geoTechs}
        isLoading={isLoading}
      />

      {heatmap && <TecnologiasHeatmap heatmap={heatmap} />}

      <TecnologiasDetalle
        items={items}
        selectedTech={selectedTech}
        onSelectTech={setSelectedTech}
        detalle={detalle}
        isLoading={detalleLoading}
        error={detalleError}
        onRetry={refetchDetalle}
      />

      <TecnologiasTabla
        filas={filteredItems}
        filter={filter}
        onFilterChange={setFilter}
        isLoading={isLoading}
      />

      {scoredItems.length > 0 && <TecnologiasTopScore items={scoredItems} />}
    </div>
  );
}
