"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Calendar, ChevronDown, Cpu, Info, ListFilter, Map, RotateCcw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { useDebounce } from "@/hooks/use-debounce";
import { useFilterParams, useFilters } from "@/lib/filters";
import { pathUsesGlobalFilters } from "@/lib/navigation";
import { useSearchHistory } from "@/lib/search-history";
import { SavedViewsMenu } from "@/components/saved-views-menu";

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

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

interface DatePreset {
  label: string;
  desde: () => string | null;
  hasta: () => string | null;
}

const DATE_PRESETS: DatePreset[] = [
  { label: "Ultimos 7 dias", desde: () => toIsoDate(new Date(Date.now() - 7 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Ultimos 30 dias", desde: () => toIsoDate(new Date(Date.now() - 30 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Ultimos 90 dias", desde: () => toIsoDate(new Date(Date.now() - 90 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Este anio (YTD)", desde: () => `${new Date().getFullYear()}-01-01`, hasta: () => toIsoDate(new Date()) },
  { label: "Ultimos 12 meses", desde: () => toIsoDate(new Date(Date.now() - 365 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Todo", desde: () => null, hasta: () => null },
];

const IMPORTE_PRESETS = [
  { label: "> 100K", value: 100_000 },
  { label: "> 500K", value: 500_000 },
  { label: "> 1M", value: 1_000_000 },
];

/** Popover minimalista con click-outside/Escape, mismo idioma que SavedViewsMenu. */
function PresetMenu({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <Button
        variant="outline"
        size="sm"
        className="h-9 gap-1 px-2 text-xs"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        title={label}
      >
        {icon}
        <ChevronDown className="h-3 w-3" />
        <span className="sr-only">{label}</span>
      </Button>
      {open && (
        <div
          role="menu"
          tabIndex={-1}
          className="tf-glass-strong absolute left-0 top-full z-50 mt-1 min-w-40 rounded-md border border-border/70 p-1 shadow-xl"
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function GlobalFilterBar() {
  const pathname = usePathname();
  const filtersApply = pathUsesGlobalFilters(pathname);
  const filters = useFilters();
  const filterParams = useFilterParams();
  const activeCount = Object.keys(filterParams).length;
  const { history, addToHistory } = useSearchHistory();
  const { data: meta } = useQuery<MetaFilters>({
    queryKey: ["meta-filters"],
    queryFn: async () => {
      const res = await fetch("/api/v1/meta/filters", { credentials: "include" });
      if (!res.ok) throw new Error("Failed to fetch filters");
      return res.json() as Promise<MetaFilters>;
    },
    staleTime: 5 * 60 * 1000,
    enabled: filtersApply,
  });

  const chips = [
    ...filters.estados.map((value) => ({ kind: "estado" as const, value })),
    ...filters.ccaas.map((value) => ({ kind: "ccaa" as const, value })),
    ...filters.tecnologias.map((value) => ({ kind: "tecnologia" as const, value })),
  ];

  // Importe: input local + debounce 400ms antes de tocar la URL/refetch —
  // antes cada tecla disparaba un refetch inmediato.
  const [importeInput, setImporteInput] = React.useState(filters.importeMin ?? "");
  const debouncedImporte = useDebounce(importeInput, 400);

  // Vistas guardadas, "Limpiar" y los presets tocan importeMin directamente;
  // reflejar el cambio en el input ajustando el estado durante el render
  // (patrón recomendado por React para derivar de un valor externo, en vez
  // de un Effect con setState síncrono) solo cuando difiere numericamente.
  const [prevExternalImporte, setPrevExternalImporte] = React.useState(filters.importeMin);
  if (filters.importeMin !== prevExternalImporte) {
    setPrevExternalImporte(filters.importeMin);
    const currentNum = importeInput === "" ? null : Number(importeInput);
    if (currentNum !== filters.importeMin) {
      setImporteInput(filters.importeMin ?? "");
    }
  }

  // Local -> externo: sincroniza el valor debounced con el estado de filtros
  // (una llamada a un setter externo, no a setState local — no cae bajo la
  // regla que desaconseja setState propio dentro de un efecto).
  React.useEffect(() => {
    const next = debouncedImporte === "" ? null : Number(debouncedImporte);
    if (next !== filters.importeMin) filters.setImporteMin(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo reacciona al valor debounced
  }, [debouncedImporte]);

  const removeChip = (kind: "estado" | "ccaa" | "tecnologia", value: string) => {
    if (kind === "estado") filters.setEstados(filters.estados.filter((item) => item !== value));
    if (kind === "ccaa") filters.setCcaas(filters.ccaas.filter((item) => item !== value));
    if (kind === "tecnologia") filters.setTecnologias(filters.tecnologias.filter((item) => item !== value));
  };

  // Contrato de filtros por página: donde no aplican, la barra no se muestra.
  // Si además hay filtros activos, lo decimos en vez de fingir que filtran.
  if (!filtersApply) {
    if (activeCount === 0) return null;
    return (
      <div className="tf-glass sticky top-[60px] z-30 flex items-center gap-2 border-b border-border/70 px-4 py-1.5 text-xs text-muted-foreground">
        <Info className="h-3.5 w-3.5 shrink-0 text-primary" />
        <span>
          Los filtros globales no aplican en esta página ({activeCount}{" "}
          {activeCount === 1 ? "activo" : "activos"}).
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={filters.resetFilters}
        >
          <RotateCcw className="h-3 w-3" />
          Limpiar
        </Button>
      </div>
    );
  }

  return (
    <div className="tf-glass sticky top-[60px] z-30 flex min-h-13 flex-wrap items-center gap-2 border-b border-border/70 px-4 py-2">
      <SearchAutocomplete
        className="min-w-56 flex-1 sm:max-w-80"
        aria-label="Buscar licitaciones"
        inputClassName="h-9 rounded-md bg-background/70 pl-9 text-xs"
        placeholder="Buscar licitaciones, organos, empresas..."
        value={filters.q}
        onChange={filters.setQ}
        onSubmit={addToHistory}
        recentSearches={history}
        leftIcon={<Search className="h-4 w-4" />}
      />

      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <Calendar className="h-3.5 w-3.5 text-primary" />
        <span className="hidden sm:inline">Desde</span>
        <input
          type="date"
          aria-label="Fecha desde"
          value={filters.rango.desde ?? ""}
          onChange={(event) => filters.setRango({ ...filters.rango, desde: event.target.value || null })}
          className="bg-transparent text-foreground outline-none"
        />
      </label>

      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <span className="hidden sm:inline">Hasta</span>
        <input
          type="date"
          aria-label="Fecha hasta"
          value={filters.rango.hasta ?? ""}
          onChange={(event) => filters.setRango({ ...filters.rango, hasta: event.target.value || null })}
          className="bg-transparent text-foreground outline-none"
        />
      </label>

      <PresetMenu icon={<Calendar className="h-3.5 w-3.5 text-primary" />} label="Rangos de fecha rapidos">
        {(close) => (
          <>
            {DATE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                role="menuitem"
                className="block w-full rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => {
                  filters.setRango({ desde: preset.desde(), hasta: preset.hasta() });
                  close();
                }}
              >
                {preset.label}
              </button>
            ))}
          </>
        )}
      </PresetMenu>

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

      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <ListFilter className="h-3.5 w-3.5 text-primary" />
        <select
          aria-label="Filtrar por estado"
          className="max-w-32 bg-inherit text-foreground outline-none"
          value=""
          onChange={(event) => addUnique(event.target.value, filters.estados, filters.setEstados)}
        >
          <option value="">Estado</option>
          {(meta?.estado ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>

      <Input
        aria-label="Importe minimo"
        type="number"
        className="h-9 w-32 rounded-md bg-background/70 text-xs"
        placeholder="Importe min."
        value={importeInput}
        onChange={(event) => setImporteInput(event.target.value ? Number(event.target.value) : "")}
      />

      <PresetMenu icon={<span className="text-xs font-semibold text-primary">€</span>} label="Presets de importe minimo">
        {(close) => (
          <>
            {IMPORTE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                role="menuitem"
                className="block w-full rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => {
                  filters.setImporteMin(preset.value);
                  close();
                }}
              >
                {preset.label}
              </button>
            ))}
            <button
              type="button"
              role="menuitem"
              className="block w-full rounded-sm px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent"
              onClick={() => {
                filters.setImporteMin(null);
                close();
              }}
            >
              Cualquiera
            </button>
          </>
        )}
      </PresetMenu>

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

      <div className="ml-auto flex items-center gap-1">
        <SavedViewsMenu />
        <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={filters.resetFilters}>
          <RotateCcw className="h-3.5 w-3.5" />
          Limpiar
        </Button>
      </div>
    </div>
  );
}
