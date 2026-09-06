"use client";

/**
 * Vista compartida por la ruta `/calendario` y por `?vista=calendario` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 */

import { Button } from "@/components/ui/button";
import { PipelineRoleNav } from "@/components/pipeline-role-nav";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { useCalendarioView } from "../_hooks/use-calendario-view";
import { CalendarioDiaSemana, CalendarioMensual } from "./calendario-graficos";
import { CalendarioHeatmap } from "./calendario-heatmap";

export default function CalendarioView() {
  const {
    weeks,
    months,
    monthlyData,
    dowData,
    availableYears,
    selectedYear,
    setSelectedYear,
    isLoading,
    error,
  } = useCalendarioView();

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">
          {"Error"}: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="sr-only">Calendario</h1>
          <p className="text-muted-foreground">
            Heatmap de publicaciones por fecha.
          </p>
        </div>

        {/* Selector de año. Los dos botones son icon-only: el SVG de lucide no
            aporta texto, así que sin `aria-label` el lector anuncia «botón» a
            secas y no hay forma de saber cuál avanza y cuál retrocede (WCAG
            4.1.2). El icono se marca `aria-hidden` para que no compita con la
            etiqueta. El año visible no sirve de nombre: vive fuera del botón. */}
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8"
            aria-label="Año anterior"
            onClick={() => setSelectedYear((y) => Math.max(availableYears[0], y - 1))}
            disabled={selectedYear <= availableYears[0]}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </Button>
          <span className="px-3 text-sm font-medium tabular-nums">{selectedYear}</span>
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8"
            aria-label="Año siguiente"
            onClick={() => setSelectedYear((y) => Math.min(availableYears[availableYears.length - 1], y + 1))}
            disabled={selectedYear >= availableYears[availableYears.length - 1]}
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <PipelineRoleNav current="calendario" />

      <CalendarioHeatmap
        weeks={weeks}
        months={months}
        selectedYear={selectedYear}
        isLoading={isLoading}
      />

      <CalendarioMensual
        data={monthlyData}
        selectedYear={selectedYear}
        isLoading={isLoading}
      />

      <CalendarioDiaSemana
        data={dowData}
        selectedYear={selectedYear}
        isLoading={isLoading}
      />
    </div>
  );
}
