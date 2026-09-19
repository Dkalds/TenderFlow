"use client";

/**
 * Vista compartida por la ruta `/calendario` y por `?vista=calendario` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 *
 * La vista principal es la de **vencimientos** (qué cierra y cuándo, RFC
 * ux-calendario #2-#4); la de publicaciones se conserva como conmutador.
 */

import { Button } from "@/components/ui/button";
import { PipelineRoleNav } from "@/components/pipeline-role-nav";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { useCalendarioView, type CalendarioModo } from "../_hooks/use-calendario-view";
import { CalendarioDiaSemana, CalendarioMensual } from "./calendario-graficos";
import { CalendarioHeatmap } from "./calendario-heatmap";
import { CalendarioVencimientosKpis, ProximosSieteDias } from "./calendario-vencimientos-kpis";

const MODOS: { valor: CalendarioModo; etiqueta: string }[] = [
  { valor: "vencimientos", etiqueta: "Vencimientos" },
  { valor: "publicaciones", etiqueta: "Publicaciones" },
];

export default function CalendarioView() {
  const {
    modo,
    setModo,
    weeks,
    months,
    monthlyData,
    dowData,
    availableYears,
    selectedYear,
    setSelectedYear,
    vencimientos,
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

  const esVencimientos = modo === "vencimientos";
  const primerAnio = availableYears[0];
  const ultimoAnio = availableYears[availableYears.length - 1];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="sr-only">Calendario</h1>
          <p className="text-muted-foreground">
            {esVencimientos
              ? "Qué licitaciones cierran su plazo de presentación, y cuándo."
              : "Heatmap de publicaciones por fecha."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Conmutador de métrica. `aria-pressed` porque son dos botones de
              estado, no navegación: el lector anuncia cuál está activo. */}
          <div className="flex items-center gap-1" role="group" aria-label="Métrica del calendario">
            {MODOS.map((m) => (
              <Button
                key={m.valor}
                variant={modo === m.valor ? "default" : "outline"}
                size="sm"
                aria-pressed={modo === m.valor}
                onClick={() => setModo(m.valor)}
              >
                {m.etiqueta}
              </Button>
            ))}
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
              onClick={() => setSelectedYear((y) => Math.max(primerAnio, y - 1))}
              disabled={selectedYear <= primerAnio}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <span className="px-3 text-sm font-medium tabular-nums">{selectedYear}</span>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              aria-label="Año siguiente"
              onClick={() => setSelectedYear((y) => Math.min(ultimoAnio, y + 1))}
              disabled={selectedYear >= ultimoAnio}
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>

      <PipelineRoleNav current="calendario" />

      {esVencimientos && <CalendarioVencimientosKpis data={vencimientos} isLoading={isLoading} />}

      {esVencimientos && !isLoading && <ProximosSieteDias weeks={weeks} />}

      <CalendarioHeatmap
        weeks={weeks}
        months={months}
        selectedYear={selectedYear}
        modo={modo}
        isLoading={isLoading}
      />

      <CalendarioMensual
        data={monthlyData}
        selectedYear={selectedYear}
        etiqueta={esVencimientos ? "Cierres" : "Publicaciones"}
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
