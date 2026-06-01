/**
 * Global filter state — shared across all dashboard pages.
 * Syncs with URL query params via nuqs for shareable URLs.
 */
import { create } from "zustand";

export interface DateRange {
  desde: string | null; // YYYY-MM-DD
  hasta: string | null;
}

export interface FiltersState {
  // Text search
  q: string;
  // Date range
  rango: DateRange;
  // Multi-selects
  estados: string[];
  ccaas: string[];
  organos: string[];
  tecnologias: string[];
  // Numeric
  importeMin: number | null;
  // Comparison mode
  comparar: boolean;
  rangoB: DateRange;

  // Actions
  setQ: (q: string) => void;
  setRango: (rango: DateRange) => void;
  setEstados: (estados: string[]) => void;
  setCcaas: (ccaas: string[]) => void;
  setOrganos: (organos: string[]) => void;
  setTecnologias: (tecnologias: string[]) => void;
  setImporteMin: (min: number | null) => void;
  setComparar: (comparar: boolean) => void;
  setRangoB: (rango: DateRange) => void;
  resetFilters: () => void;
}

const initialState = {
  q: "",
  rango: { desde: null, hasta: null } as DateRange,
  estados: [] as string[],
  ccaas: [] as string[],
  organos: [] as string[],
  tecnologias: [] as string[],
  importeMin: null as number | null,
  comparar: false,
  rangoB: { desde: null, hasta: null } as DateRange,
};

export const useFilters = create<FiltersState>((set) => ({
  ...initialState,
  setQ: (q) => set({ q }),
  setRango: (rango) => set({ rango }),
  setEstados: (estados) => set({ estados }),
  setCcaas: (ccaas) => set({ ccaas }),
  setOrganos: (organos) => set({ organos }),
  setTecnologias: (tecnologias) => set({ tecnologias }),
  setImporteMin: (importeMin) => set({ importeMin }),
  setComparar: (comparar) => set({ comparar }),
  setRangoB: (rangoB) => set({ rangoB }),
  resetFilters: () => set(initialState),
}));

/** Filter state without action methods. */
export type FilterValues = typeof initialState;

/**
 * Convert current filter state to API query params.
 * Only includes non-empty/non-null values.
 *
 * NOTE: Multi-value filters are sent as comma-separated strings.
 * The backend GET endpoints need to split on "," for multi-value
 * support (currently only POST /search handles arrays natively).
 */
export function filtersToParams(filters: FilterValues): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.q) params.q = filters.q;
  if (filters.rango.desde) params.fecha_desde = filters.rango.desde;
  if (filters.rango.hasta) params.fecha_hasta = filters.rango.hasta;
  if (filters.estados.length) params.estado = filters.estados.join(",");
  if (filters.ccaas.length) params.ccaa = filters.ccaas.join(",");
  if (filters.tecnologias.length) params.tecnologia = filters.tecnologias.join(",");
  if (filters.importeMin !== null) params.importe_min = String(filters.importeMin);
  return params;
}

/**
 * Hook to get filter params ready for API calls.
 */
export function useFilterParams(): Record<string, string> {
  const { q, rango, estados, ccaas, organos, tecnologias, importeMin, comparar, rangoB } =
    useFilters();
  return filtersToParams({ q, rango, estados, ccaas, organos, tecnologias, importeMin, comparar, rangoB });
}
