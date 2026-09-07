"use client";

import { Download, GitCompareArrows, Star, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * Barra flotante de selección.
 *
 * Aparece sólo con filas marcadas y agrupa lo que se hace *en bloque*: comparar
 * (2 o 3, que es lo que el comparador sabe pintar), exportar la selección y
 * seguirla entera.
 */
export function DetalleSeleccion({
  seleccionadas,
  onComparar,
  onExportar,
  onSeguir,
  onLimpiar,
}: {
  seleccionadas: number;
  onComparar: () => void;
  onExportar: () => void;
  onSeguir: () => void;
  onLimpiar: () => void;
}) {
  if (seleccionadas === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[68px] z-40 flex justify-center">
      <div className="tf-glass-strong pointer-events-auto flex items-center gap-2 rounded-xl border border-border/70 px-3.5 py-2.5 shadow-xl animate-in fade-in-0 slide-in-from-bottom-2 duration-[260ms]">
        <span className="tf-tnum text-[12.5px] font-semibold">{seleccionadas} seleccionadas</span>
        <span className="h-4.5 w-px bg-border/70" aria-hidden="true" />
        <Tooltip>
          {/* El disparador es el `span`, no el `Button`: cuando el botón
              está deshabilitado no emite eventos de puntero, y justo ahí es
              cuando hace falta explicar por qué. `focusin` sí burbujea, así
              que con el botón activo el tooltip también abre con teclado. */}
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2.5 text-xs"
                onClick={onComparar}
                disabled={seleccionadas < 2 || seleccionadas > 3}
              >
                <GitCompareArrows className="h-3.5 w-3.5" />
                Comparar ({seleccionadas})
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>Comparar 2 o 3 licitaciones</TooltipContent>
        </Tooltip>
        <Button variant="outline" size="sm" className="h-7 px-2.5 text-xs" onClick={onExportar}>
          <Download className="h-3.5 w-3.5" />
          Exportar selección
        </Button>
        <Button variant="outline" size="sm" className="h-7 px-2.5 text-xs" onClick={onSeguir}>
          <Star className="h-3.5 w-3.5" />
          Seguir
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 px-0"
          aria-label="Limpiar selección"
          onClick={onLimpiar}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
