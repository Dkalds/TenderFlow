"use client";

/**
 * Vista compartida por la ruta `/tecnologias` y por `?vista=tecnologias` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 */

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
    scoredItems,
    filter,
    setFilter,
    selectedTech,
    setSelectedTech,
    trendMetric,
    setTrendMetric,
    isLoading,
    error,
  } = useTecnologiasView();

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
          <h1 className="sr-only">Tecnologías</h1>
          <p className="text-muted-foreground">
            Distribución, evolución y cruces por tecnología detectada.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "tecnologias" }}
        />
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
