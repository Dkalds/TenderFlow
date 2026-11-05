"use client";

import * as React from "react";
import { Search } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { ETIQUETA_CAMPO } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { FiltrosListadoEditor } from "@/components/layout/scope-filtros-listado";
import { useDebounce } from "@/hooks/use-debounce";
import type { MetaFilters } from "@/hooks/use-meta-filters";
import type { ValorDiferido } from "@/hooks/use-valor-diferido";
import { estadoLabel } from "@/lib/estados";
import { useFilters } from "@/lib/filters";
import type { GlobalFilterKey } from "@/lib/navigation";
import { useSearchHistory } from "@/lib/search-history";
import { cn } from "@/lib/utils";

/**
 * El editor del ámbito, tras «+ Añadir» de la barra (`scope-bar.tsx`): los
 * seis controles que antes vivían sueltos en la barra (búsqueda, fechas con
 * presets, CCAA, tecnología, estado e importe con presets) y los filtros
 * opt-in de las pantallas que los declaran.
 */

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

const DATE_PRESETS = [
  {
    label: "Últimos 7 días",
    desde: () => toIsoDate(new Date(Date.now() - 7 * 86400000)),
    hasta: () => toIsoDate(new Date()),
  },
  {
    label: "Últimos 30 días",
    desde: () => toIsoDate(new Date(Date.now() - 30 * 86400000)),
    hasta: () => toIsoDate(new Date()),
  },
  {
    label: "Últimos 90 días",
    desde: () => toIsoDate(new Date(Date.now() - 90 * 86400000)),
    hasta: () => toIsoDate(new Date()),
  },
  { label: "Este año (YTD)", desde: () => `${new Date().getFullYear()}-01-01`, hasta: () => toIsoDate(new Date()) },
  {
    label: "Últimos 12 meses",
    desde: () => toIsoDate(new Date(Date.now() - 365 * 86400000)),
    hasta: () => toIsoDate(new Date()),
  },
  { label: "Todo", desde: () => null, hasta: () => null },
];

const IMPORTE_PRESETS = [
  { label: "> 100K", value: 100_000 },
  { label: "> 500K", value: 500_000 },
  { label: "> 1M", value: 1_000_000 },
];

/**
 * Atajos de valor del editor (periodos, importes). Pequeños pero con la diana
 * mínima de 24 px (WCAG 2.5.8); `tf-pressable` ya anima el color y la
 * pulsación.
 */
const PRESET =
  "tf-pressable inline-flex h-6 items-center rounded-md border border-divider px-2 text-tf-micro text-muted-foreground hover:border-primary-line-strong hover:text-foreground";

/** Editor del ámbito: los seis controles que antes vivían sueltos en la barra. */
export function ScopeEditor({
  meta,
  shows,
  singleTecnologia,
  busqueda,
}: {
  meta: MetaFilters | undefined;
  shows: (key: GlobalFilterKey) => boolean;
  singleTecnologia: boolean;
  /**
   * El texto de búsqueda vive en la barra y no aquí: el editor se desmonta al
   * cerrarse, y cerrarlo antes de que venza la espera perdería lo tecleado.
   */
  busqueda: ValorDiferido<string>;
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

  const label = cn(ETIQUETA_CAMPO, "mb-1.5");
  const control = "h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground";

  return (
    <div className="space-y-3 p-1">
      {shows("q") && (
        <div>
          <span className={label}>Búsqueda</span>
          {/* Cada tecla cambia sólo el campo; la URL recibe el valor cuando se
              deja de teclear (`RETRASO_BUSQUEDA_MS`), o en el acto con Enter o
              al elegir una búsqueda reciente. */}
          <SearchAutocomplete
            aria-label="Buscar licitaciones"
            inputClassName="h-8 rounded-md bg-background pl-8 text-xs"
            placeholder="Licitaciones, órganos, empresas…"
            value={busqueda.valor}
            onChange={busqueda.cambiar}
            onSubmit={(valor) => {
              busqueda.aplicarYa(valor);
              addToHistory(valor);
            }}
            recentSearches={history}
            leftIcon={<Search className="h-3.5 w-3.5" aria-hidden="true" />}
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
              onChange={(event) => filters.setRango({ ...filters.rango, desde: event.target.value || null })}
              className={control}
            />
            <input
              type="date"
              aria-label="Fecha hasta"
              value={filters.rango.hasta ?? ""}
              onChange={(event) => filters.setRango({ ...filters.rango, hasta: event.target.value || null })}
              className={control}
            />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {DATE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => filters.setRango({ desde: preset.desde(), hasta: preset.hasta() })}
                className={PRESET}
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
            // `/meta/filters` devuelve los códigos de la columna, no etiquetas:
            // sin esto el desplegable ofrecía "AGR" y "EJEC" como opciones.
            optionLabel={estadoLabel}
          />
          {/* Separado del multi-select porque no es un código más: descarta los
              estados terminales, cualesquiera que sean. Marcar "PUB" y "EV" a
              mano no es equivalente — deja fuera `ADM` y cualquier código que
              la fuente publique mañana. */}
          <div className="mt-1.5 flex items-center gap-2">
            {/* `htmlFor`/`id` en vez de envolver el control: el Checkbox de Radix
                renderiza un `<button role="checkbox">`, no un input nativo, así
                que anidarlo no lo asocia con la etiqueta. */}
            <Checkbox
              id="scope-solo-abiertas"
              checked={filters.soloAbiertas}
              onCheckedChange={(value) => filters.setSoloAbiertas(value === true)}
            />
            <label htmlFor="scope-solo-abiertas" className="text-tf-meta text-muted-foreground cursor-pointer">
              Sólo abiertas
              <span className="text-tf-micro ml-1">(sin adjudicar ni cerrar)</span>
            </label>
          </div>
        </div>
      )}

      {shows("importe") && (
        <div>
          <span className={label}>Importe mínimo</span>
          <Input
            aria-label="Importe mínimo"
            type="number"
            className="bg-background h-8 w-full text-xs"
            placeholder="Sin mínimo"
            value={importeInput}
            onChange={(event) => setImporteInput(event.target.value ? Number(event.target.value) : "")}
          />
          <div className="mt-1.5 flex flex-wrap gap-1">
            {IMPORTE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => filters.setImporteMin(preset.value)}
                className={PRESET}
              >
                {preset.label}
              </button>
            ))}
            <button type="button" onClick={() => filters.setImporteMin(null)} className={PRESET}>
              Cualquiera
            </button>
          </div>
        </div>
      )}

      {/* F1.1 — sólo en las pantallas que los declaran (opt-in). */}
      <FiltrosListadoEditor filters={filters} meta={meta} shows={shows} />
    </div>
  );
}
