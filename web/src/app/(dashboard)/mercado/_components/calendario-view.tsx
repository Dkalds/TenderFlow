"use client";

/**
 * Vista compartida por la ruta `/calendario` y por `?vista=calendario` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 *
 * La vista principal es la de **vencimientos** (qué cierra y cuándo, RFC
 * ux-calendario #2-#4); la de publicaciones se conserva como conmutador.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";

import { PanelError, Segmented } from "@/components/console/panel";
import { Button } from "@/components/ui/button";

import { useCalendarioView, type CalendarioModo } from "../_hooks/use-calendario-view";
import { CalendarioDiaSemana, CalendarioMensual } from "./calendario-graficos";
import { CalendarioHeatmap } from "./calendario-heatmap";
import { CalendarioVencimientosKpis, ProximosSieteDias } from "./calendario-vencimientos-kpis";

const MODOS: { value: CalendarioModo; label: string }[] = [
  { value: "vencimientos", label: "Vencimientos" },
  { value: "publicaciones", label: "Publicaciones" },
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
    refetch,
  } = useCalendarioView();

  if (error) {
    return <PanelError title="No se pudo cargar el calendario" error={error} onRetry={refetch} />;
  }

  const esVencimientos = modo === "vencimientos";
  const primerAnio = availableYears[0];
  const ultimoAnio = availableYears[availableYears.length - 1];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="sr-only">Calendario</h1>
          <p className="text-tf-meta text-muted-foreground">
            {esVencimientos
              ? "Qué licitaciones cierran su plazo de presentación, y cuándo."
              : "Cuántas licitaciones se publican cada día."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Conmutador de métrica. `aria-pressed` porque son dos botones de
              estado, no navegación: el lector anuncia cuál está activo. */}
          <Segmented value={modo} onChange={setModo} options={MODOS} aria-label="Métrica del calendario" />

          {/* Selector de año. Los dos botones son icon-only: el SVG de lucide no
              aporta texto, así que sin `aria-label` el lector anuncia «botón» a
              secas y no hay forma de saber cuál avanza y cuál retrocede (WCAG
              4.1.2). El icono se marca `aria-hidden` para que no compita con la
              etiqueta. El año visible no sirve de nombre: vive fuera del botón. */}
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Año anterior"
              onClick={() => setSelectedYear((y) => Math.max(primerAnio, y - 1))}
              disabled={selectedYear <= primerAnio}
            >
              <ChevronLeft aria-hidden="true" />
            </Button>
            <span className="px-2 text-tf-body font-medium">{selectedYear}</span>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Año siguiente"
              onClick={() => setSelectedYear((y) => Math.min(ultimoAnio, y + 1))}
              disabled={selectedYear >= ultimoAnio}
            >
              <ChevronRight aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>

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
