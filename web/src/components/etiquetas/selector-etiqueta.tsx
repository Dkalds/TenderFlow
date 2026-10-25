"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Etiqueta } from "@/hooks/use-etiquetas";
import { cn } from "@/lib/utils";
import { TODAS_LAS_ETIQUETAS } from "./filtro-etiqueta";

/**
 * El desplegable de `FiltroEtiquetaSelect` (`filtro-etiqueta.tsx`).
 *
 * Módulo propio para que Radix Select llegue solo cuando hay algo que elegir:
 * el filtro no se pinta hasta que la organización tiene etiquetas, y eso solo
 * se sabe en el navegador. Sin esto viajaba en el First Load de Detalle, el
 * Radar y Oportunidades para quien no ha creado ninguna.
 */
export function SelectorEtiqueta({
  etiquetas,
  value,
  onChange,
  alcance,
  className,
}: {
  etiquetas: readonly Etiqueta[];
  value: string;
  onChange: (filtro: string) => void;
  alcance?: string;
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        className={cn("h-7 w-44 text-tf-meta", className)}
        aria-label={alcance ? `Filtrar por etiqueta ${alcance}` : "Filtrar por etiqueta"}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={TODAS_LAS_ETIQUETAS}>Todas las etiquetas</SelectItem>
        {etiquetas.map((etiqueta) => (
          <SelectItem key={etiqueta.id} value={String(etiqueta.id)}>
            {etiqueta.nombre}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
