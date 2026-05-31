"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Cpu, Map, RotateCcw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useFilters } from "@/lib/filters";

interface MetaFilters {
  estado: string[];
  ccaa: string[];
  tecnologia: string[];
  cpv: string[];
}

function addUnique(value: string, current: string[], setValue: (value: string[]) => void) {
  if (!value || current.includes(value)) return;
  setValue([...current, value]);
}

export function GlobalFilterBar() {
  const filters = useFilters();
  const { data: meta } = useQuery<MetaFilters>({
    queryKey: ["meta-filters"],
    queryFn: async () => {
      const res = await fetch("/api/v1/meta/filters", { credentials: "include" });
      if (!res.ok) throw new Error("Failed to fetch filters");
      return res.json() as Promise<MetaFilters>;
    },
    staleTime: 5 * 60 * 1000,
  });

  const chips = [
    ...filters.estados.map((value) => ({ kind: "estado" as const, value })),
    ...filters.ccaas.map((value) => ({ kind: "ccaa" as const, value })),
    ...filters.tecnologias.map((value) => ({ kind: "tecnologia" as const, value })),
  ];

  const removeChip = (kind: "estado" | "ccaa" | "tecnologia", value: string) => {
    if (kind === "estado") filters.setEstados(filters.estados.filter((item) => item !== value));
    if (kind === "ccaa") filters.setCcaas(filters.ccaas.filter((item) => item !== value));
    if (kind === "tecnologia") filters.setTecnologias(filters.tecnologias.filter((item) => item !== value));
  };

  return (
    <div className="sticky top-[60px] z-30 flex min-h-13 flex-wrap items-center gap-2 border-b border-border/70 bg-card/95 px-4 py-2 backdrop-blur">
      <div className="relative min-w-56 flex-1 sm:max-w-80">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          aria-label="Buscar licitaciones"
          className="h-9 rounded-md bg-background/70 pl-9 text-xs"
          placeholder="Buscar licitaciones, organos, empresas..."
          value={filters.q}
          onChange={(event) => filters.setQ(event.target.value)}
        />
      </div>

      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <Calendar className="h-3.5 w-3.5 text-primary" />
        <span className="hidden sm:inline">Desde</span>
        <input
          type="date"
          value={filters.rango.desde ?? ""}
          onChange={(event) => filters.setRango({ ...filters.rango, desde: event.target.value || null })}
          className="bg-transparent text-foreground outline-none"
        />
      </label>

      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <span className="hidden sm:inline">Hasta</span>
        <input
          type="date"
          value={filters.rango.hasta ?? ""}
          onChange={(event) => filters.setRango({ ...filters.rango, hasta: event.target.value || null })}
          className="bg-transparent text-foreground outline-none"
        />
      </label>

      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <Map className="h-3.5 w-3.5 text-primary" />
        <select
          aria-label="Filtrar por CCAA"
          className="max-w-36 bg-inherit text-foreground outline-none"
          value=""
          onChange={(event) => addUnique(event.target.value, filters.ccaas, filters.setCcaas)}
        >
          <option value="">CCAA</option>
          {(meta?.ccaa ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>

      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <Cpu className="h-3.5 w-3.5 text-primary" />
        <select
          aria-label="Filtrar por tecnologia"
          className="max-w-40 bg-inherit text-foreground outline-none"
          value=""
          onChange={(event) => addUnique(event.target.value, filters.tecnologias, filters.setTecnologias)}
        >
          <option value="">Tecnologia</option>
          {(meta?.tecnologia ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>

      <Input
        aria-label="Importe minimo"
        type="number"
        className="h-9 w-32 rounded-md bg-background/70 text-xs"
        placeholder="Importe min."
        value={filters.importeMin ?? ""}
        onChange={(event) => filters.setImporteMin(event.target.value ? Number(event.target.value) : null)}
      />

      {chips.map((chip) => (
        <span
          key={`${chip.kind}-${chip.value}`}
          className="inline-flex h-8 items-center gap-1 rounded-full border border-primary/10 bg-primary/10 px-3 text-xs font-semibold text-primary"
        >
          {chip.value}
          <button type="button" aria-label={`Quitar ${chip.value}`} onClick={() => removeChip(chip.kind, chip.value)}>
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}

      <Button variant="ghost" size="sm" className="ml-auto h-8 px-2 text-xs" onClick={filters.resetFilters}>
        <RotateCcw className="h-3.5 w-3.5" />
        Limpiar
      </Button>
    </div>
  );
}
