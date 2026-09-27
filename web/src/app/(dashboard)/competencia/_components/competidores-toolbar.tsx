"use client";

/**
 * Barra de ámbito de Competidores: buscador y exportación.
 *
 * El buscador filtra la tabla **y los nueve cortes**, y eso antes había que
 * descubrirlo probando; el distintivo junto al campo lo dice mientras hay
 * término escrito. Exportar arrastra el ámbito activo, no la vista.
 */

import { ExportPopover } from "@/components/export-popover";
import { Badge } from "@/components/ui/badge";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Search } from "lucide-react";

export function CompetidoresToolbar({
  search,
  onSearchChange,
  suggestions,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  /** Nombres del dataset ya descargado; no se piden aparte. */
  suggestions: string[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <SearchAutocomplete
        className="w-full sm:w-72"
        placeholder="Buscar empresa…"
        value={search}
        onChange={onSearchChange}
        suggestions={suggestions}
        leftIcon={<Search className="h-3.5 w-3.5" aria-hidden="true" />}
        inputClassName="h-8 pl-8 text-tf-meta md:h-7"
      />
      {search.trim() && (
        <Badge variant="default" size="sm">
          Filtra la tabla y los 9 cortes
        </Badge>
      )}
      <div className="flex-1" />
      <ExportPopover extraParams={{ section: "competitors" }} label="Exportar competidores" />
    </div>
  );
}
