"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Calendar, RotateCcw } from "lucide-react";
import { useFilters } from "@/lib/filters";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";

interface MetaFilters {
  estado: string[];
  ccaa: string[];
  tecnologia: string[];
  cpv: string[];
}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

interface CheckboxGroupProps {
  label: string;
  options: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
}

function CheckboxGroup({ label, options, selected, onChange }: CheckboxGroupProps) {
  const toggle = (val: string) => {
    onChange(
      selected.includes(val)
        ? selected.filter((s) => s !== val)
        : [...selected, val],
    );
  };

  return (
    <details className="group">
      <summary className="flex cursor-pointer items-center justify-between py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground select-none">
        {label}
        {selected.length > 0 && (
          <span className="ml-1 rounded-full bg-primary/10 px-1.5 text-xs font-semibold text-primary">
            {selected.length}
          </span>
        )}
      </summary>
      <div className="max-h-40 space-y-0.5 overflow-y-auto pl-1 pb-1">
        {options.map((opt) => (
          <label
            key={opt}
            className="flex items-center gap-2 rounded px-1 py-2 text-xs hover:bg-accent cursor-pointer"
          >
            <input
              type="checkbox"
              checked={selected.includes(opt)}
              onChange={() => toggle(opt)}
              className="h-5 w-5 rounded border-muted-foreground"
            />
            <span className="truncate">{opt}</span>
          </label>
        ))}
        {options.length === 0 && (
          <span className="text-xs text-muted-foreground italic">Sin opciones</span>
        )}
      </div>
    </details>
  );
}

export function FiltersSidebar({ className }: { className?: string }) {
  const filters = useFilters();
  const [localQ, setLocalQ] = React.useState(filters.q);
  const debouncedQ = useDebounce(localQ, 300);

  React.useEffect(() => {
    filters.setQ(debouncedQ);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  // Sync local q when store resets
  React.useEffect(() => {
    if (filters.q === "" && localQ !== "") setLocalQ("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.q]);

  const { data: meta } = useQuery<MetaFilters>({
    queryKey: ["meta-filters"],
    queryFn: async () => {
      const res = await fetch("/api/v1/meta/filters", { credentials: "include" });
      if (!res.ok) throw new Error("Failed to fetch filters");
      return res.json() as Promise<MetaFilters>;
    },
    staleTime: 5 * 60 * 1000,
  });

  return (
    <ScrollArea className={cn("flex flex-col gap-3", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Filtros
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-9 px-2 text-xs"
          onClick={() => {
            filters.resetFilters();
            setLocalQ("");
          }}
        >
          <RotateCcw className="mr-1 h-3 w-3" />
          Limpiar
        </Button>
      </div>

      <Separator />

      {/* Text search */}
      <div className="space-y-1">
        <label htmlFor="filter-search" className="text-xs text-muted-foreground flex items-center gap-1">
          <Search className="h-3 w-3" /> Buscar
        </label>
        <Input
          id="filter-search"
          placeholder="Texto libre..."
          value={localQ}
          onChange={(e) => setLocalQ(e.target.value)}
          className="h-9 text-xs"
        />
      </div>

      <Separator />

      {/* Date range */}
      <div className="space-y-1">
        <label htmlFor="filter-date-from" className="text-xs text-muted-foreground flex items-center gap-1">
          <Calendar className="h-3 w-3" /> Rango de fechas
        </label>
        <div className="flex gap-1">
          <Input
            id="filter-date-from"
            type="date"
            value={filters.rango.desde ?? ""}
            onChange={(e) =>
              filters.setRango({ ...filters.rango, desde: e.target.value || null })
            }
            className="h-9 text-xs flex-1"
          />
          <Input
            id="filter-date-to"
            type="date"
            value={filters.rango.hasta ?? ""}
            onChange={(e) =>
              filters.setRango({ ...filters.rango, hasta: e.target.value || null })
            }
            className="h-9 text-xs flex-1"
          />
        </div>
      </div>

      <Separator />

      {/* Multi-selects */}
      <CheckboxGroup
        label="Estados"
        options={meta?.estado ?? []}
        selected={filters.estados}
        onChange={filters.setEstados}
      />

      <CheckboxGroup
        label="CCAA"
        options={meta?.ccaa ?? []}
        selected={filters.ccaas}
        onChange={filters.setCcaas}
      />

      <CheckboxGroup
        label="Tecnologias"
        options={meta?.tecnologia ?? []}
        selected={filters.tecnologias}
        onChange={filters.setTecnologias}
      />

      <Separator />

      {/* Importe min */}
      <div className="space-y-1">
        <label htmlFor="filter-importe-min" className="text-xs text-muted-foreground">Importe minimo</label>
        <Input
          id="filter-importe-min"
          type="number"
          placeholder="0"
          value={filters.importeMin ?? ""}
          onChange={(e) =>
            filters.setImporteMin(e.target.value ? Number(e.target.value) : null)
          }
          className="h-9 text-xs"
        />
      </div>

      <Separator />

      {/* Comparison mode */}
      <label htmlFor="filter-comparar" className="flex items-center gap-2 text-xs cursor-pointer">
        <input
          id="filter-comparar"
          type="checkbox"
          checked={filters.comparar}
          onChange={(e) => filters.setComparar(e.target.checked)}
          className="h-5 w-5 rounded"
        />
        Modo comparacion
      </label>

      {filters.comparar && (
        <div className="space-y-1 pl-2 border-l-2 border-primary/20">
          <label htmlFor="filter-range-b-from" className="text-xs text-muted-foreground flex items-center gap-1">
            <Calendar className="h-3 w-3" /> Rango B
          </label>
          <div className="flex gap-1">
            <Input
              id="filter-range-b-from"
              type="date"
              value={filters.rangoB.desde ?? ""}
              onChange={(e) =>
                filters.setRangoB({ ...filters.rangoB, desde: e.target.value || null })
              }
              className="h-9 text-xs flex-1"
            />
            <Input
              id="filter-range-b-to"
              type="date"
              value={filters.rangoB.hasta ?? ""}
              onChange={(e) =>
                filters.setRangoB({ ...filters.rangoB, hasta: e.target.value || null })
              }
              className="h-9 text-xs flex-1"
            />
          </div>
        </div>
      )}
    </ScrollArea>
  );
}
