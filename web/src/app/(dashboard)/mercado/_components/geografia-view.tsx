"use client";

/**
 * Vista compartida por la ruta `/geografia` y por `?vista=geografia` del espacio
 * Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo no vive
 * en el `page.tsx` de la ruta.
 */

import { ExportPopover } from "@/components/export-popover";

import { useGeografiaView } from "../_hooks/use-geografia-view";
import { GeografiaGraficos } from "./geografia-graficos";
import { GeografiaKpis } from "./geografia-kpis";
import { GeografiaMapa } from "./geografia-mapa";
import { GeografiaTablaCcaa, GeografiaTablaProvincias } from "./geografia-tablas";

export default function GeografiaView() {
  const {
    items,
    topCcaa,
    top3Concentration,
    ccaaMayorTicket,
    mapData,
    mapMetric,
    setMapMetric,
    barData,
    pieData,
    sortedItems,
    sortKey,
    sortDir,
    toggleSort,
    sortedProvincias,
    provSortKey,
    provSortDir,
    toggleProvSort,
    activeCcaa,
    toggleCcaa,
    isLoading,
    error,
  } = useGeografiaView();

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
          <h1 className="sr-only">Geografía</h1>
          <p className="text-muted-foreground">
            Distribución geográfica por Comunidad Autónoma.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "geografia" }}
        />
      </div>

      <GeografiaKpis
        topCcaa={topCcaa}
        top3Concentration={top3Concentration}
        totalCcaas={items.length}
        ccaaMayorTicket={ccaaMayorTicket}
        isLoading={isLoading}
      />

      <GeografiaMapa
        data={mapData}
        metric={mapMetric}
        onMetricChange={setMapMetric}
        onCcaaClick={toggleCcaa}
        isLoading={isLoading}
      />

      <GeografiaGraficos
        barData={barData}
        pieData={pieData}
        onSelect={toggleCcaa}
        isLoading={isLoading}
      />

      <GeografiaTablaCcaa
        filas={sortedItems}
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={toggleSort}
        activeCcaa={activeCcaa}
        onToggleCcaa={toggleCcaa}
        isLoading={isLoading}
      />

      <GeografiaTablaProvincias
        filas={sortedProvincias}
        sortKey={provSortKey}
        sortDir={provSortDir}
        onSort={toggleProvSort}
        isLoading={isLoading}
      />
    </div>
  );
}
