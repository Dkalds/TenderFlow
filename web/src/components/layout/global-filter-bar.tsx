"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Calendar, ChevronDown, Cpu, Info, ListFilter, Map, RotateCcw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Input } from "@/components/ui/input";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { useDebounce } from "@/hooks/use-debounce";
import { useScrolledPast } from "@/hooks/use-scrolled-past";
import { useFilterParams, useFilters } from "@/lib/filters";
import { cn } from "@/lib/utils";
import { pageGlobalFilterKeys, pathUsesGlobalFilters } from "@/lib/navigation";
import { useSearchHistory } from "@/lib/search-history";
import { SavedViewsMenu } from "@/components/saved-views-menu";
import { useAnnounceOnChange } from "@/components/live-region";

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
  { label: "Últimos 7 días", desde: () => toIsoDate(new Date(Date.now() - 7 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Últimos 30 días", desde: () => toIsoDate(new Date(Date.now() - 30 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Últimos 90 días", desde: () => toIsoDate(new Date(Date.now() - 90 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Este año (YTD)", desde: () => `${new Date().getFullYear()}-01-01`, hasta: () => toIsoDate(new Date()) },
  { label: "Últimos 12 meses", desde: () => toIsoDate(new Date(Date.now() - 365 * 86400000)), hasta: () => toIsoDate(new Date()) },
  { label: "Todo", desde: () => null, hasta: () => null },
];

const IMPORTE_PRESETS = [
  { label: "> 100K", value: 100_000 },
  { label: "> 500K", value: 500_000 },
  { label: "> 1M", value: 1_000_000 },
];

/** Small preset dropdown (date ranges, importe presets) — a plain option
 *  list with no form control, so `DropdownMenu` (unlike `SavedViewsMenu`,
 *  which needs `Popover` for its text input — see components/ui/popover.tsx)
 *  is the right primitive: exit animation, focus trap, and Escape/outside
 *  dismissal come for free instead of being hand-rolled. */
function PresetMenu({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-9 gap-1 px-2 text-xs"
              aria-haspopup="menu"
            >
              {icon}
              <ChevronDown className="h-3 w-3" />
              <span className="sr-only">{label}</span>
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="start" className="min-w-40">
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function GlobalFilterBar() {
  const pathname = usePathname();
  // Subconjunto de filtros de la página (o null = todos). Una página puede
  // aplicar solo algunos filtros aunque no consuma el resto del estado global
  // (p. ej. Renovaciones solo filtra por tecnología): en ese caso la barra se
  // muestra con esos controles únicamente, en vez de ocultarse por completo.
  const subsetKeys = pageGlobalFilterKeys(pathname);
  const filtersApply =
    pathUsesGlobalFilters(pathname) || (subsetKeys?.length ?? 0) > 0;
  const shows = (
    key: "q" | "fecha" | "ccaa" | "tecnologia" | "estado" | "importe",
  ) => !subsetKeys || subsetKeys.includes(key);
  const filters = useFilters();
  const filterParams = useFilterParams();
  const activeCount = Object.keys(filterParams).length;

  // Aplicar o quitar un filtro repinta la página entera sin decir nada a un
  // lector de pantalla. El recuento de resultados lo anuncia cada tabla; esto
  // anuncia el cambio de criterio, que es lo que el usuario acaba de hacer.
  useAnnounceOnChange(
    filtersApply
      ? activeCount === 0
        ? "Sin filtros activos"
        : `${activeCount} ${activeCount === 1 ? "filtro activo" : "filtros activos"}`
      : null,
  );
  const { history, addToHistory } = useSearchHistory();
  const scrolled = useScrolledPast(8);
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
    ...(shows("estado") ? filters.estados.map((value) => ({ kind: "estado" as const, value })) : []),
    ...(shows("ccaa") ? filters.ccaas.map((value) => ({ kind: "ccaa" as const, value })) : []),
    ...(shows("tecnologia")
      ? filters.tecnologias.map((value) => ({ kind: "tecnologia" as const, value }))
      : []),
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
    <div
      className={cn(
        "tf-glass sticky top-[60px] z-30 flex min-h-13 items-center gap-2 border-b border-border/70 px-4 py-2",
        // Al scrollear, la barra deja de envolverse en 2-3 filas y pasa a una
        // sola con scroll horizontal. Con 8 controles más un chip por filtro
        // activo, el `flex-wrap` permanente costaba ~80px fijos de altura en una
        // barra pegajosa, encima de un contenido que son tablas y grafos.
        // Mismo gesto que el KPI bar, que ya usa este hook.
        scrolled
          ? "flex-nowrap overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          : "flex-wrap",
      )}
    >
      {shows("q") && (
      <SearchAutocomplete
        className="min-w-56 flex-1 sm:max-w-80"
        data-search-input
        aria-label="Buscar licitaciones"
        inputClassName="h-9 rounded-md bg-background/70 pl-9 text-xs"
        placeholder="Buscar licitaciones, órganos, empresas…"
        value={filters.q}
        onChange={filters.setQ}
        onSubmit={addToHistory}
        recentSearches={history}
        leftIcon={<Search className="h-4 w-4" />}
      />
      )}

      {shows("fecha") && (
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
      )}

      {shows("fecha") && (
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
      )}

      {shows("fecha") && (
      <PresetMenu icon={<Calendar className="h-3.5 w-3.5 text-primary" />} label="Rangos de fecha rápidos">
        {DATE_PRESETS.map((preset) => (
          <DropdownMenuItem
            key={preset.label}
            onSelect={() => filters.setRango({ desde: preset.desde(), hasta: preset.hasta() })}
          >
            {preset.label}
          </DropdownMenuItem>
        ))}
      </PresetMenu>
      )}

      {shows("ccaa") && (
      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <Map className="h-3.5 w-3.5 text-primary" />
        <select
          aria-label="Filtrar por comunidad autónoma"
          className="max-w-36 bg-inherit text-foreground outline-none"
          value=""
          onChange={(event) => addUnique(event.target.value, filters.ccaas, filters.setCcaas)}
        >
          <option value="">CCAA</option>
          {(meta?.ccaa ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      )}

      {shows("tecnologia") && (
      <label className="inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-background/70 px-3 text-xs text-muted-foreground">
        <Cpu className="h-3.5 w-3.5 text-primary" />
        <select
          aria-label="Filtrar por tecnología"
          className="max-w-40 bg-inherit text-foreground outline-none"
          value=""
          onChange={(event) => addUnique(event.target.value, filters.tecnologias, filters.setTecnologias)}
        >
          <option value="">Tecnología</option>
          {(meta?.tecnologia ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      )}

      {shows("estado") && (
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
      )}

      {shows("importe") && (
      <Input
        aria-label="Importe mínimo"
        type="number"
        className="h-9 w-32 rounded-md bg-background/70 text-xs"
        placeholder="Importe mín."
        value={importeInput}
        onChange={(event) => setImporteInput(event.target.value ? Number(event.target.value) : "")}
      />
      )}

      {shows("importe") && (
      <PresetMenu icon={<span className="text-xs font-semibold text-primary">€</span>} label="Atajos de importe mínimo">
        {IMPORTE_PRESETS.map((preset) => (
          <DropdownMenuItem key={preset.label} onSelect={() => filters.setImporteMin(preset.value)}>
            {preset.label}
          </DropdownMenuItem>
        ))}
        <DropdownMenuItem
          className="text-muted-foreground"
          onSelect={() => filters.setImporteMin(null)}
        >
          Cualquiera
        </DropdownMenuItem>
      </PresetMenu>
      )}

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
