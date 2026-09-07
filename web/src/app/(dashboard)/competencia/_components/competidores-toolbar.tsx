"use client";

/**
 * Barra de ámbito de Competidores: buscador y exportación.
 *
 * El buscador filtra la tabla **y los nueve cortes**, y eso antes había que
 * descubrirlo probando; el distintivo junto al campo lo dice mientras hay
 * término escrito. Exportar arrastra el ámbito activo, no la vista.
 */

import { ExportPopover } from "@/components/export-popover";
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
        leftIcon={<Search className="h-4 w-4" />}
        inputClassName="h-8 pl-9 text-xs"
      />
      {search.trim() && (
        <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-1 text-[10.5px] font-medium text-primary">
          filtra la tabla y los 9 cortes
        </span>
      )}
      <div className="flex-1" />
      <ExportPopover
        extraParams={{ section: "competitors" }}
        className="[&>button]:h-8 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs"
      />
    </div>
  );
}
