"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Info, Redo2, RotateCcw, Search, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { SavedViewsMenu } from "@/components/saved-views-menu";
import { ExportPopover } from "@/components/export-popover";
import { NotificationBell } from "@/components/notification-bell";
import { useAnnounceOnChange } from "@/components/live-region";
import { useDebounce } from "@/hooks/use-debounce";
import { useDataFreshness } from "@/hooks/use-data-freshness";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters, useFilterParams } from "@/lib/filters";
import { useScopeHistory } from "@/lib/scope-history";
import { useSearchHistory } from "@/lib/search-history";
import { useUiStore } from "@/lib/ui-store";
import {
  pageGlobalFilterKeys,
  pageSingleValueFilterKeys,
  pathUsesGlobalFilters,
  type GlobalFilterKey,
} from "@/lib/navigation";
import { cn, formatNumber } from "@/lib/utils";

/**
 * Barra de ámbito — 52px, el objeto de contexto persistente.
 *
 * Reemplaza a la `GlobalFilterBar` de ocho `<select>` sueltos. El ámbito pasa
 * a ser **un objeto**: chips con clave y valor, deshacer/rehacer siempre
 * visibles, y un editor único tras «+ Añadir» que conserva los seis controles
 * de la barra anterior (búsqueda, fechas con presets, CCAA, tecnología, estado
 * e importe con presets). Nada de lo que había desaparece: cambia de sitio.
 *
 * El contrato por página se respeta igual que antes (`lib/navigation.ts`): una
 * página que no consume filtros no ve chips inertes, y si hay filtros activos
 * se dice en vez de fingir que aplican.
 */

interface MetaFilters {
  estado: string[];
  ccaa: string[];
  tecnologia: string[];
  cpv: string[];
}

interface OverviewData {
  total_licitaciones: number;
}

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

const DATE_PRESETS = [
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

interface Chip {
  key: string;
  value: string;
  remove: () => void;
}

const NAV_BUTTON =
  "grid h-6 w-6 place-items-center rounded-md border text-[12px] transition-colors duration-140 ease-out";

function ScopeChip({ chip }: { chip: Chip }) {
  return (
    <span className="inline-flex h-[26px] items-center gap-[7px] rounded-md border border-primary/30 bg-primary/10 px-2 text-primary">
      <span className="font-mono text-[9px] font-medium uppercase leading-none tracking-[0.06em] opacity-60">
        {chip.key}
      </span>
      <span className="max-w-40 truncate text-xs font-medium leading-none">{chip.value}</span>
      <button
        type="button"
        aria-label={`Quitar ${chip.key.toLowerCase()} ${chip.value}`}
        onClick={chip.remove}
        className="cursor-pointer border-0 bg-transparent p-0 pl-px text-[13px] leading-none opacity-50 transition-opacity duration-140 ease-out hover:opacity-100"
      >
        ×
      </button>
    </span>
  );
}

/** Editor del ámbito: los seis controles que antes vivían sueltos en la barra. */
function ScopeEditor({
  meta,
  shows,
  singleTecnologia,
}: {
  meta: MetaFilters | undefined;
  shows: (key: GlobalFilterKey) => boolean;
  singleTecnologia: boolean;
}) {
  const filters = useFilters();
  const { history, addToHistory } = useSearchHistory();

  // Importe: input local con debounce de 400ms antes de tocar la URL, igual que
  // en la barra anterior — sin él cada tecla dispara un refetch.
  const [importeInput, setImporteInput] = React.useState<number | "">(filters.importeMin ?? "");
  const debouncedImporte = useDebounce(importeInput, 400);
  const [prevExternalImporte, setPrevExternalImporte] = React.useState(filters.importeMin);
  if (filters.importeMin !== prevExternalImporte) {
    setPrevExternalImporte(filters.importeMin);
    const currentNum = importeInput === "" ? null : Number(importeInput);
    if (currentNum !== filters.importeMin) setImporteInput(filters.importeMin ?? "");
  }
  React.useEffect(() => {
    const next = debouncedImporte === "" ? null : Number(debouncedImporte);
    if (next !== filters.importeMin) filters.setImporteMin(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo reacciona al valor debounced
  }, [debouncedImporte]);

  const label = "mb-1.5 block font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground";
  const control =
    "h-8 w-full rounded-md border border-input bg-background/70 px-2 text-xs text-foreground outline-none";

  return (
    <div className="space-y-3 p-1">
      {shows("q") && (
        <div>
          <span className={label}>Búsqueda</span>
          <SearchAutocomplete
            aria-label="Buscar licitaciones"
            inputClassName="h-8 rounded-md bg-background/70 pl-8 text-xs"
            placeholder="Licitaciones, órganos, empresas…"
            value={filters.q}
            onChange={filters.setQ}
            onSubmit={addToHistory}
            recentSearches={history}
            leftIcon={<Search className="h-3.5 w-3.5" />}
          />
        </div>
      )}

      {shows("fecha") && (
        <div>
          <span className={label}>Periodo</span>
          <div className="flex items-center gap-1.5">
            <input
              type="date"
              aria-label="Fecha desde"
              value={filters.rango.desde ?? ""}
              onChange={(event) =>
                filters.setRango({ ...filters.rango, desde: event.target.value || null })
              }
              className={control}
            />
            <input
              type="date"
              aria-label="Fecha hasta"
              value={filters.rango.hasta ?? ""}
              onChange={(event) =>
                filters.setRango({ ...filters.rango, hasta: event.target.value || null })
              }
              className={control}
            />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {DATE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => filters.setRango({ desde: preset.desde(), hasta: preset.hasta() })}
                className="tf-pressable rounded border border-border/70 px-1.5 py-1 text-[10px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {shows("ccaa") && (
        <div>
          <span className={label}>Comunidad autónoma</span>
          <MultiSelect
            aria-label="Añadir comunidad autónoma al ámbito"
            options={meta?.ccaa ?? []}
            selected={filters.ccaas}
            onChange={filters.setCcaas}
            placeholder="Añadir CCAA…"
          />
        </div>
      )}

      {shows("tecnologia") && (
        <div>
          <span className={label}>Tecnología</span>
          <MultiSelect
            aria-label="Filtrar por tecnología"
            options={meta?.tecnologia ?? []}
            selected={filters.tecnologias}
            onChange={filters.setTecnologias}
            placeholder={singleTecnologia ? "Todas" : "Añadir tecnología…"}
            single={singleTecnologia}
          />
        </div>
      )}

      {shows("estado") && (
        <div>
          <span className={label}>Estado</span>
          <MultiSelect
            aria-label="Añadir estado al ámbito"
            options={meta?.estado ?? []}
            selected={filters.estados}
            onChange={filters.setEstados}
            placeholder="Añadir estado…"
          />
        </div>
      )}

      {shows("importe") && (
        <div>
          <span className={label}>Importe mínimo</span>
          <Input
            aria-label="Importe mínimo"
            type="number"
            className="h-8 w-full rounded-md bg-background/70 text-xs"
            placeholder="Sin mínimo"
            value={importeInput}
            onChange={(event) =>
              setImporteInput(event.target.value ? Number(event.target.value) : "")
            }
          />
          <div className="mt-1.5 flex flex-wrap gap-1">
            {IMPORTE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => filters.setImporteMin(preset.value)}
                className="tf-pressable rounded border border-border/70 px-1.5 py-1 text-[10px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
              >
                {preset.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => filters.setImporteMin(null)}
              className="tf-pressable rounded border border-border/70 px-1.5 py-1 text-[10px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
            >
              Cualquiera
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ScopeBar() {
  const pathname = usePathname();
  const filters = useFilters();
  const filterParams = useFilterParams();
  const activeCount = Object.keys(filterParams).length;
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const { relative } = useDataFreshness();
  const { canUndo, canRedo, undo, redo } = useScopeHistory();
  const [editorOpen, setEditorOpen] = React.useState(false);

  const subsetKeys = pageGlobalFilterKeys(pathname);
  const singleValueKeys = pageSingleValueFilterKeys(pathname);
  const filtersApply = pathUsesGlobalFilters(pathname) || (subsetKeys?.length ?? 0) > 0;
  const shows = React.useCallback(
    (key: GlobalFilterKey) => !subsetKeys || subsetKeys.includes(key),
    [subsetKeys],
  );

  useAnnounceOnChange(
    filtersApply
      ? activeCount === 0
        ? "Sin filtros activos"
        : `${activeCount} ${activeCount === 1 ? "filtro activo" : "filtros activos"}`
      : null,
  );

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

  // Recuento del ámbito: el mismo dataset y la misma clave de query que el KPI
  // bar, para que no puedan discrepar sobre cuántas licitaciones hay dentro.
  const { data: overview, isLoading: countLoading } = useFilteredQuery<OverviewData>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 60_000, retry: 1, enabled: filtersApply },
  );

  const chips: Chip[] = React.useMemo(() => {
    const list: Chip[] = [];
    if (shows("q") && filters.q) {
      list.push({ key: "Busca", value: filters.q, remove: () => filters.setQ("") });
    }
    if (shows("fecha") && (filters.rango.desde || filters.rango.hasta)) {
      const desde = filters.rango.desde ?? "…";
      const hasta = filters.rango.hasta ?? "hoy";
      list.push({
        key: "Periodo",
        value: `${desde} → ${hasta}`,
        remove: () => filters.setRango({ desde: null, hasta: null }),
      });
    }
    if (shows("estado")) {
      for (const value of filters.estados) {
        list.push({
          key: "Estado",
          value,
          remove: () => filters.setEstados(filters.estados.filter((item) => item !== value)),
        });
      }
    }
    if (shows("ccaa")) {
      for (const value of filters.ccaas) {
        list.push({
          key: "CCAA",
          value,
          remove: () => filters.setCcaas(filters.ccaas.filter((item) => item !== value)),
        });
      }
    }
    if (shows("tecnologia")) {
      for (const value of filters.tecnologias) {
        list.push({
          key: "Tecnología",
          value,
          remove: () => filters.setTecnologias(filters.tecnologias.filter((item) => item !== value)),
        });
      }
    }
    if (shows("importe") && filters.importeMin != null) {
      list.push({
        key: "Importe",
        value: `> ${formatNumber(filters.importeMin)} €`,
        remove: () => filters.setImporteMin(null),
      });
    }
    return list;
  }, [filters, shows]);

  // Contrato de filtros por página: donde no aplican, no se pintan chips que no
  // filtran nada. Si además hay filtros activos, se dice.
  if (!filtersApply) {
    return (
      <header className="tf-glass sticky top-0 z-30 flex h-[52px] flex-none items-center gap-2.5 border-b border-border/70 px-3.5">
        {activeCount > 0 ? (
          <>
            <Info className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
            <span className="text-xs text-muted-foreground">
              El ámbito global no aplica en esta pantalla ({activeCount}{" "}
              {activeCount === 1 ? "filtro activo" : "filtros activos"}).
            </span>
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={filters.resetFilters}>
              <RotateCcw className="h-3 w-3" />
              Limpiar
            </Button>
          </>
        ) : (
          <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Ámbito · no aplica en esta pantalla
          </span>
        )}
        <div className="flex-1" />
        <ScopeUtilities onSearch={() => setCommandOpen(true)} relative={relative} />
      </header>
    );
  }

  return (
    <header className="tf-glass sticky top-0 z-30 flex h-[52px] flex-none items-center gap-2.5 overflow-x-auto border-b border-border/70 px-3.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <div className="flex flex-none items-center gap-1.5 border-r border-border/70 pr-2.5">
        <button
          type="button"
          onClick={undo}
          disabled={!canUndo}
          title="Deshacer cambio de ámbito"
          aria-label="Deshacer cambio de ámbito"
          className={cn(
            NAV_BUTTON,
            canUndo
              ? "cursor-pointer border-border/80 text-muted-foreground hover:text-foreground"
              : "cursor-default border-border/40 text-muted-foreground/40",
          )}
        >
          <Undo2 className="h-3 w-3" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={redo}
          disabled={!canRedo}
          title="Rehacer cambio de ámbito"
          aria-label="Rehacer cambio de ámbito"
          className={cn(
            NAV_BUTTON,
            canRedo
              ? "cursor-pointer border-border/80 text-muted-foreground hover:text-foreground"
              : "cursor-default border-border/40 text-muted-foreground/40",
          )}
        >
          <Redo2 className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>

      <span className="flex-none font-mono text-[9px] font-semibold uppercase leading-none tracking-[0.14em] text-muted-foreground">
        Ámbito
      </span>

      <div className="flex min-w-0 items-center gap-1.5">
        {chips.map((chip) => (
          <ScopeChip key={`${chip.key}-${chip.value}`} chip={chip} />
        ))}

        <Popover open={editorOpen} onOpenChange={setEditorOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-haspopup="dialog"
              className="inline-flex h-[26px] flex-none cursor-pointer items-center gap-1.5 rounded-md border border-dashed border-border bg-transparent px-2.5 text-xs font-medium text-muted-foreground transition-colors duration-140 ease-out hover:border-primary/50 hover:text-foreground"
            >
              + Añadir
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80">
            <ScopeEditor
              meta={meta}
              shows={shows}
              singleTecnologia={singleValueKeys.includes("tecnologia")}
            />
            {activeCount > 0 && (
              <div className="mt-1 border-t border-border/70 pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-full justify-start px-2 text-xs"
                  onClick={filters.resetFilters}
                >
                  <RotateCcw className="h-3 w-3" />
                  Limpiar el ámbito
                </Button>
              </div>
            )}
          </PopoverContent>
        </Popover>
      </div>

      <div className="flex-1" />

      <div className="flex flex-none items-center gap-[7px] text-[11px] text-muted-foreground">
        <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
          <span className="absolute inset-0 rounded-full bg-[hsl(var(--success))] opacity-60 motion-safe:animate-ping" />
          <span className="relative h-1.5 w-1.5 rounded-full bg-[hsl(var(--success))]" />
        </span>
        <span className="tf-tnum">
          {countLoading || !overview
            ? "—"
            : `${formatNumber(overview.total_licitaciones)} licitaciones`}
        </span>
        <span className="opacity-40" aria-hidden="true">
          ·
        </span>
        <span>{relative ? `sync ${relative}` : "sin registro de sync"}</span>
      </div>

      <SavedViewsMenu />

      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => setCommandOpen(true)}
            aria-label="Abrir búsqueda y comandos"
            className="inline-flex h-7 flex-none cursor-pointer items-center gap-1.5 rounded-md border border-border/80 bg-transparent px-2.5 text-xs text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground"
          >
            Buscar
            <span className="rounded border border-border/70 px-1 py-0.5 font-mono text-[9px] leading-none">
              ⌘K
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent>Buscar licitaciones, órganos, empresas…</TooltipContent>
      </Tooltip>

      <div className="flex flex-none items-center gap-1 border-l border-border/70 pl-2.5">
        {/* «Exportar ámbito», no «Exportar» a secas: varias pantallas tienen su
            propia exportación con el corte de esa sección, y dos botones con la
            misma etiqueta a cuatro dedos de distancia no se distinguen. Este
            saca lo que gobierna esta barra — el ámbito activo. */}
        <ExportPopover
          label="Exportar ámbito"
          className="[&>button]:h-7 [&>button]:px-2 [&>button]:py-0 [&>button]:text-xs"
        />
        <NotificationBell />
      </div>
    </header>
  );
}

/** Cluster de utilidades para las pantallas sin ámbito (mismo alineado). */
function ScopeUtilities({
  onSearch,
  relative,
}: {
  onSearch: () => void;
  relative: string | null;
}) {
  return (
    <>
      <span className="flex-none text-[11px] text-muted-foreground">
        {relative ? `sync ${relative}` : "sin registro de sync"}
      </span>
      <button
        type="button"
        onClick={onSearch}
        aria-label="Abrir búsqueda y comandos"
        className="inline-flex h-7 flex-none cursor-pointer items-center gap-1.5 rounded-md border border-border/80 bg-transparent px-2.5 text-xs text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground"
      >
        Buscar
        <span className="rounded border border-border/70 px-1 py-0.5 font-mono text-[9px] leading-none">
          ⌘K
        </span>
      </button>
      <div className="flex flex-none items-center gap-1 border-l border-border/70 pl-2.5">
        <ExportPopover className="[&>button]:h-7 [&>button]:px-2 [&>button]:py-0 [&>button]:text-xs" />
        <NotificationBell />
      </div>
    </>
  );
}
