"use client";

import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Etiqueta } from "@/hooks/use-etiquetas";

export const TODAS = "todas";

/**
 * Los dos controles que gobiernan las seis columnas. Viven en la cabecera del
 * espacio, no dentro del tablero: filtran todo a la vez, no una columna.
 */
export function TableroFiltros({
  query,
  onQuery,
  etiqueta,
  onEtiqueta,
  etiquetas,
}: {
  query: string;
  onQuery: (valor: string) => void;
  etiqueta: string;
  onEtiqueta: (valor: string) => void;
  etiquetas: readonly Etiqueta[];
}) {
  return (
    <div className="flex flex-none items-center gap-2">
      {etiquetas.length > 0 ? (
        <Select value={etiqueta} onValueChange={onEtiqueta}>
          <SelectTrigger className="h-7 w-44 text-tf-meta" aria-label="Filtrar por etiqueta">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={TODAS}>Todas las etiquetas</SelectItem>
            {etiquetas.map((item) => (
              <SelectItem key={item.id} value={String(item.id)}>
                {item.nombre}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
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
