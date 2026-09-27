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
      <div className="tf-glass-strong pointer-events-auto flex items-center gap-2 rounded-xl border border-border/70 px-3.5 py-2.5 shadow-md animate-in fade-in-0 slide-in-from-bottom-2">
        <span className="tf-tnum text-tf-body font-semibold">{seleccionadas} seleccionadas</span>
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
                onClick={onComparar}
                disabled={seleccionadas < 2 || seleccionadas > 3}
              >
                <GitCompareArrows aria-hidden="true" />
                Comparar ({seleccionadas})
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>Comparar 2 o 3 licitaciones</TooltipContent>
        </Tooltip>
        <Button variant="outline" size="sm" onClick={onExportar}>
          <Download aria-hidden="true" />
          Exportar selección
        </Button>
        <Button variant="outline" size="sm" onClick={onSeguir}>
          <Star aria-hidden="true" />
          Seguir
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Limpiar selección" onClick={onLimpiar}>
          <X aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
