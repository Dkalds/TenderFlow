"use client";

import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { FiltroEtiquetaSelect } from "@/components/etiquetas/filtro-etiqueta";
import { ExportarCrm } from "./exportar-crm";

/**
 * Los controles que gobiernan las seis columnas. Viven en la cabecera del
 * espacio, no dentro del tablero: filtran todo a la vez, no una columna.
 *
 * El filtro de etiqueta es el compartido con el Radar y Detalle
 * (`components/etiquetas/filtro-etiqueta.tsx`), no una copia: pide sus propias
 * etiquetas y desaparece cuando la organización no tiene ninguna.
 */
export function TableroFiltros({
  query,
  onQuery,
  etiqueta,
  onEtiqueta,
}: {
  query: string;
  onQuery: (valor: string) => void;
  etiqueta: string;
  onEtiqueta: (valor: string) => void;
}) {
  return (
    <div className="flex flex-none items-center gap-2">
      {/* F6.3 — el tablero entero como CSV para el CRM. */}
      <ExportarCrm />
      <FiltroEtiquetaSelect value={etiqueta} onChange={onEtiqueta} alcance="en el tablero" />
      <label className="relative block w-56 flex-none" htmlFor="pursuit-search">
        <Search
          className="text-muted-foreground pointer-events-none absolute top-1.5 left-2.5 h-3.5 w-3.5"
          aria-hidden="true"
        />
        <span className="sr-only">Buscar oportunidad</span>
        <Input
          id="pursuit-search"
          className="h-7 pl-8 text-tf-meta"
          placeholder="Título, referencia o responsable"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
      </label>
    </div>
  );
}
