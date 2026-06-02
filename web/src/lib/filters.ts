/**
 * Global filter state — synced with URL query params via nuqs.
 * Filters persist across page refreshes and are shareable via URL.
 */
import { parseAsString, useQueryStates } from "nuqs";
import { useCallback, useMemo } from "react";

export interface DateRange {
  desde: string | null; // YYYY-MM-DD
  hasta: string | null;
}

export interface FiltersState {
  q: string;
  rango: DateRange;
  estados: string[];
  ccaas: string[];
  tecnologias: string[];
  importeMin: number | null;
  comparar: boolean;
  rangoB: DateRange;

  setQ: (q: string) => void;
  setRango: (rango: DateRange) => void;
  setEstados: (estados: string[]) => void;
  setCcaas: (ccaas: string[]) => void;
  setTecnologias: (tecnologias: string[]) => void;
  setImporteMin: (min: number | null) => void;
  setComparar: (comparar: boolean) => void;
  setRangoB: (rango: DateRange) => void;
  resetFilters: () => void;
}

/** Filter values without action methods. */
export interface FilterValues {
  q: string;
  rango: DateRange;
  estados: string[];
  ccaas: string[];
  tecnologias: string[];
  importeMin: number | null;
}

const filterParsers = {
  q: parseAsString.withDefault(""),
  fecha_desde: parseAsString.withDefault(""),
  fecha_hasta: parseAsString.withDefault(""),
  estado: parseAsString.withDefault(""),
  ccaa: parseAsString.withDefault(""),
  tecnologia: parseAsString.withDefault(""),
  importe_min: parseAsString.withDefault(""),
  comparar: parseAsString.withDefault(""),
  rango_b_desde: parseAsString.withDefault(""),
  rango_b_hasta: parseAsString.withDefault(""),
};

export function useFilters(): FiltersState {
  const [params, setParams] = useQueryStates(filterParsers, {
    history: "push",
    shallow: false,
  });

  const rango = useMemo(
    () => ({
      desde: params.fecha_desde || null,
      hasta: params.fecha_hasta || null,
    }),
    [params.fecha_desde, params.fecha_hasta],
  );

  const setRango = useCallback(
    (r: DateRange) =>
      setParams({ fecha_desde: r.desde || "", fecha_hasta: r.hasta || "" }),
    [setParams],
  );

  const estados = useMemo(
    () => (params.estado ? params.estado.split(",") : []),
    [params.estado],
  );

  const setEstados = useCallback(
    (estados: string[]) => setParams({ estado: estados.join(",") || "" }),
    [setParams],
  );

  const ccaas = useMemo(
    () => (params.ccaa ? params.ccaa.split(",") : []),
    [params.ccaa],
  );

  const setCcaas = useCallback(
    (ccaas: string[]) => setParams({ ccaa: ccaas.join(",") || "" }),
    [setParams],
  );

  const tecnologias = useMemo(
    () => (params.tecnologia ? params.tecnologia.split(",") : []),
    [params.tecnologia],
  );

  const setTecnologias = useCallback(
    (tecnologias: string[]) => setParams({ tecnologia: tecnologias.join(",") || "" }),
    [setParams],
  );

  const importeMin = useMemo(
    () => (params.importe_min ? Number(params.importe_min) : null),
    [params.importe_min],
  );

  const setImporteMin = useCallback(
    (val: number | null) => setParams({ importe_min: val != null ? String(val) : "" }),
    [setParams],
  );

  const comparar = params.comparar === "true";

  const setComparar = useCallback(
    (val: boolean) => setParams({ comparar: val ? "true" : "" }),
    [setParams],
  );

  const rangoB = useMemo(
    () => ({
      desde: params.rango_b_desde || null,
      hasta: params.rango_b_hasta || null,
    }),
    [params.rango_b_desde, params.rango_b_hasta],
  );

  const setRangoB = useCallback(
    (r: DateRange) =>
      setParams({ rango_b_desde: r.desde || "", rango_b_hasta: r.hasta || "" }),
    [setParams],
  );

  const setQ = useCallback(
    (q: string) => setParams({ q: q || "" }),
    [setParams],
  );

  const resetFilters = useCallback(
    () =>
      setParams({
        q: "",
        fecha_desde: "",
        fecha_hasta: "",
        estado: "",
        ccaa: "",
        tecnologia: "",
        importe_min: "",
        comparar: "",
        rango_b_desde: "",
        rango_b_hasta: "",
      }),
    [setParams],
  );

  return {
    q: params.q,
    setQ,
    rango,
    setRango,
    estados,
    setEstados,
    ccaas,
    setCcaas,
    tecnologias,
    setTecnologias,
    importeMin,
    setImporteMin,
    comparar,
    setComparar,
    rangoB,
    setRangoB,
    resetFilters,
  };
}

/**
 * Convert current filter state to API query params.
 * Only includes non-empty/non-null values.
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
  const { q, rango, estados, ccaas, tecnologias, importeMin } = useFilters();
  return filtersToParams({ q, rango, estados, ccaas, tecnologias, importeMin });
}
