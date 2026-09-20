/**
 * Global filter state — synced with URL query params via nuqs.
 * Filters persist across page refreshes and are shareable via URL.
 */
import { parseAsString, useQueryStates } from "nuqs";
import { useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { type DateRange, filtersToParams } from "./filter-params";

// La derivación pura (URL → parámetros de API) vive en `filter-params.ts` para
// que el prefetch en servidor la comparta sin importar `nuqs` ni hooks.
export type { DateRange, FilterValues } from "./filter-params";
export { filtersToParams } from "./filter-params";

export interface FiltersState {
  q: string;
  rango: DateRange;
  estados: string[];
  ccaas: string[];
  tecnologias: string[];
  importeMin: number | null;
  soloAbiertas: boolean;
  /** F1.1 — sólo el listado los aplica (ver `FilterValues`). */
  procedimientos: string[];
  provincias: string[];
  importeMax: number | null;
  comparar: boolean;
  rangoB: DateRange;

  setQ: (q: string) => void;
  setRango: (rango: DateRange) => void;
  setEstados: (estados: string[]) => void;
  setCcaas: (ccaas: string[]) => void;
  setTecnologias: (tecnologias: string[]) => void;
  setImporteMin: (min: number | null) => void;
  setSoloAbiertas: (soloAbiertas: boolean) => void;
  setProcedimientos: (procedimientos: string[]) => void;
  setProvincias: (provincias: string[]) => void;
  setImporteMax: (max: number | null) => void;
  setComparar: (comparar: boolean) => void;
  setRangoB: (rango: DateRange) => void;
  resetFilters: () => void;
}

/** Filter values without action methods. */
const filterParsers = {
  q: parseAsString.withDefault(""),
  fecha_desde: parseAsString.withDefault(""),
  fecha_hasta: parseAsString.withDefault(""),
  estado: parseAsString.withDefault(""),
  ccaa: parseAsString.withDefault(""),
  tecnologia: parseAsString.withDefault(""),
  importe_min: parseAsString.withDefault(""),
  solo_abiertas: parseAsString.withDefault(""),
  procedimiento: parseAsString.withDefault(""),
  provincia: parseAsString.withDefault(""),
  importe_max: parseAsString.withDefault(""),
  comparar: parseAsString.withDefault(""),
  rango_b_desde: parseAsString.withDefault(""),
  rango_b_hasta: parseAsString.withDefault(""),
};

export function useFilters(): FiltersState {
  // shallow: true → la actualización de la URL es client-only e inmediata. Ningún
  //   Server Component consume estos params (todas las páginas del dashboard son
  //   "use client" y leen los filtros vía React Query en `useFilteredQuery`), así
  //   que `shallow: false` solo añadía una navegación al servidor por cada cambio
  //   de filtro → lag/carrera que obligaba a re-seleccionar para que "cuajara".
  // history: "replace" → evita un entry de historial por cada ajuste de filtro
  //   (el botón "atrás" vuelve a la página anterior, no al filtro anterior).
  const [params, setParams] = useQueryStates(filterParsers, {
    history: "replace",
    shallow: true,
  });

  const rango = useMemo(
    () => ({
      desde: params.fecha_desde || null,
      hasta: params.fecha_hasta || null,
    }),
    [params.fecha_desde, params.fecha_hasta],
  );

  const setRango = useCallback(
    (r: DateRange) => setParams({ fecha_desde: r.desde || "", fecha_hasta: r.hasta || "" }),
    [setParams],
  );

  const estados = useMemo(() => (params.estado ? params.estado.split(",") : []), [params.estado]);

  const setEstados = useCallback((estados: string[]) => setParams({ estado: estados.join(",") || "" }), [setParams]);

  const ccaas = useMemo(() => (params.ccaa ? params.ccaa.split(",") : []), [params.ccaa]);

  const setCcaas = useCallback((ccaas: string[]) => setParams({ ccaa: ccaas.join(",") || "" }), [setParams]);

  const tecnologias = useMemo(() => (params.tecnologia ? params.tecnologia.split(",") : []), [params.tecnologia]);

  const setTecnologias = useCallback(
    (tecnologias: string[]) => setParams({ tecnologia: tecnologias.join(",") || "" }),
    [setParams],
  );

  const importeMin = useMemo(() => (params.importe_min ? Number(params.importe_min) : null), [params.importe_min]);

  const setImporteMin = useCallback(
    (val: number | null) => setParams({ importe_min: val != null ? String(val) : "" }),
    [setParams],
  );

  const soloAbiertas = params.solo_abiertas === "true";

  const setSoloAbiertas = useCallback((val: boolean) => setParams({ solo_abiertas: val ? "true" : "" }), [setParams]);

  const procedimientos = useMemo(
    () => (params.procedimiento ? params.procedimiento.split(",") : []),
    [params.procedimiento],
  );
  const setProcedimientos = useCallback(
    (valores: string[]) => setParams({ procedimiento: valores.join(",") || "" }),
    [setParams],
  );

  const provincias = useMemo(() => (params.provincia ? params.provincia.split(",") : []), [params.provincia]);
  const setProvincias = useCallback(
    (valores: string[]) => setParams({ provincia: valores.join(",") || "" }),
    [setParams],
  );

  const importeMax = useMemo(() => (params.importe_max ? Number(params.importe_max) : null), [params.importe_max]);
  const setImporteMax = useCallback(
    (val: number | null) => setParams({ importe_max: val != null ? String(val) : "" }),
    [setParams],
  );

  const comparar = params.comparar === "true";

  const setComparar = useCallback((val: boolean) => setParams({ comparar: val ? "true" : "" }), [setParams]);

  const rangoB = useMemo(
    () => ({
      desde: params.rango_b_desde || null,
      hasta: params.rango_b_hasta || null,
    }),
    [params.rango_b_desde, params.rango_b_hasta],
  );

  const setRangoB = useCallback(
    (r: DateRange) => setParams({ rango_b_desde: r.desde || "", rango_b_hasta: r.hasta || "" }),
    [setParams],
  );

  const setQ = useCallback((q: string) => setParams({ q: q || "" }), [setParams]);

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
        solo_abiertas: "",
        procedimiento: "",
        provincia: "",
        importe_max: "",
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
    soloAbiertas,
    setSoloAbiertas,
    procedimientos,
    setProcedimientos,
    provincias,
    setProvincias,
    importeMax,
    setImporteMax,
    comparar,
    setComparar,
    rangoB,
    setRangoB,
    resetFilters,
  };
}

/**
 * Instantánea completa del ámbito: el valor crudo de los once parámetros que
 * gobierna el estado de filtros. Es lo que apila el historial de deshacer /
 * rehacer de la barra de ámbito (`lib/scope-history.ts`), que necesita
 * restaurar el objeto entero y no una clave suelta.
 */
export type ScopeSnapshot = Record<keyof typeof filterParsers, string>;

const SCOPE_KEYS = Object.keys(filterParsers) as (keyof typeof filterParsers)[];

export const EMPTY_SCOPE: ScopeSnapshot = Object.fromEntries(SCOPE_KEYS.map((key) => [key, ""])) as ScopeSnapshot;

/** Serialización estable de una instantánea, para comparar sin `deepEqual`. */
export function scopeKey(snapshot: ScopeSnapshot): string {
  return SCOPE_KEYS.map((key) => `${key}=${snapshot[key] ?? ""}`).join("&");
}

/**
 * Lee y escribe el ámbito completo de una vez. Separado de `useFilters` porque
 * el historial restaura los once parámetros en una sola actualización de URL:
 * hacerlo con los setters individuales produciría once entradas de historial y
 * once refetch en cascada.
 */
export function useScopeSnapshot(): {
  snapshot: ScopeSnapshot;
  applySnapshot: (next: ScopeSnapshot) => void;
} {
  const [params, setParams] = useQueryStates(filterParsers, {
    history: "replace",
    shallow: true,
  });

  // Se memoiza contra la serialización del ámbito, no contra el objeto de
  // `params`: así la instantánea mantiene identidad estable mientras el ámbito
  // no cambie de verdad, que es lo que el historial necesita para no apilar una
  // entrada por render. Mismo patrón `join()` que `useFilterParams` más abajo.
  const serialized = JSON.stringify(SCOPE_KEYS.map((key) => params[key] ?? ""));
  const snapshot = useMemo(
    () => Object.fromEntries(SCOPE_KEYS.map((key) => [key, params[key] ?? ""])) as ScopeSnapshot,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- dep primitiva estable
    [serialized],
  );

  const applySnapshot = useCallback(
    (next: ScopeSnapshot) => {
      setParams(Object.fromEntries(SCOPE_KEYS.map((key) => [key, next[key] ?? ""])) as ScopeSnapshot);
    },
    [setParams],
  );

  return { snapshot, applySnapshot };
}

/** URL param keys owned by the global filter state. */
const FILTER_PARAM_KEYS = Object.keys(filterParsers);

/**
 * Current filter query string (with leading "?"), or "" when no filter is set.
 * Lets navigation links carry the active filters across page changes so that
 * jumping between pages doesn't silently reset them.
 */
export function useFiltersQueryString(): string {
  const searchParams = useSearchParams();
  return useMemo(() => {
    const next = new URLSearchParams();
    for (const key of FILTER_PARAM_KEYS) {
      const value = searchParams.get(key);
      if (value) next.set(key, value);
    }
    const qs = next.toString();
    return qs ? `?${qs}` : "";
  }, [searchParams]);
}

/**
 * Append a filter query string to a navigation path. Paths that already carry
 * their own query string (deep-links that open a specific filtered view) are
 * returned untouched so they keep overriding the active filters.
 */
export function appendFiltersToPath(path: string, qs: string): string {
  return qs && !path.includes("?") ? `${path}${qs}` : path;
}

/**
 * Fusiona el ámbito activo con los parámetros que el propio enlace ya trae.
 *
 * Es la otra mitad de {@link appendFiltersToPath}, que devuelve intacto
 * cualquier path con query — pensado para el deep-link que quiere *sustituir*
 * el ámbito. Las tarjetas del Resumen necesitan lo contrario: cuentan dentro
 * del ámbito activo y su enlace tiene que abrir **ese mismo** subconjunto, más
 * su propio recorte. Con `appendFiltersToPath`, «Total activas» contaba las
 * abiertas de Madrid y abría las abiertas de España.
 *
 * Los parámetros del path ganan a los del ámbito: si la tarjeta fija
 * `fecha_desde=ayer`, esa fecha es su razón de existir y no la del chip.
 */
export function mergeFiltersIntoPath(path: string, qs: string): string {
  if (!qs) return path;
  const [base, ownQuery = ""] = path.split("?");
  const merged = new URLSearchParams(qs.startsWith("?") ? qs.slice(1) : qs);
  for (const [key, value] of new URLSearchParams(ownQuery)) merged.set(key, value);
  const next = merged.toString();
  return next ? `${base}?${next}` : base;
}

/**
 * Como {@link useWithFilters}, pero fusionando en vez de descartar el ámbito
 * cuando el destino trae su propia query (ver {@link mergeFiltersIntoPath}).
 */
export function useScopedHref(): (path: string) => string {
  const qs = useFiltersQueryString();
  return useCallback((path: string) => mergeFiltersIntoPath(path, qs), [qs]);
}

/**
 * Returns a helper that appends the active filters to a navigation path so
 * page-to-page navigation preserves them (see {@link appendFiltersToPath}).
 */
export function useWithFilters(): (path: string) => string {
  const qs = useFiltersQueryString();
  return useCallback((path: string) => appendFiltersToPath(path, qs), [qs]);
}

/**
 * Hook to get filter params ready for API calls.
 * Returns a stable reference (via JSON serialization) so React Query
 * doesn't refetch on every render.
 */
export function useFilterParams(): Record<string, string> {
  const {
    q,
    rango,
    estados,
    ccaas,
    tecnologias,
    importeMin,
    soloAbiertas,
    procedimientos,
    provincias,
    importeMax,
  } = useFilters();
  // Serialize arrays to strings so object identity doesn't cause unnecessary recalculations
  const estadosKey = estados.join();
  const ccaasKey = ccaas.join();
  const tecnologiasKey = tecnologias.join();
  const procedimientosKey = procedimientos.join();
  const provinciasKey = provincias.join();
  return useMemo(
    () =>
      filtersToParams({
        q,
        rango,
        estados,
        ccaas,
        tecnologias,
        importeMin,
        soloAbiertas,
        procedimientos,
        provincias,
        importeMax,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable primitive deps via join()
    [
      q,
      rango.desde,
      rango.hasta,
      estadosKey,
      ccaasKey,
      tecnologiasKey,
      importeMin,
      soloAbiertas,
      procedimientosKey,
      provinciasKey,
      importeMax,
    ],
  );
}
