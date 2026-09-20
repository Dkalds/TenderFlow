/**
 * La parte pura del ámbito global: de la URL a los parámetros de la API.
 *
 * Vive fuera de `lib/filters.ts` porque ese módulo importa `nuqs` y los hooks
 * de React, y un Server Component no puede importarlo. El prefetch en servidor
 * (`lib/server-prefetch.ts`) necesita calcular **la misma** query que calculará
 * `useFilteredQuery` en el navegador: si las dos derivaciones divergen, la
 * clave hidratada no coincide con la que pide el cliente y el prefetch se paga
 * sin servir de nada. Por eso hay una sola implementación, y `filters.ts` la
 * reexporta.
 */

export interface DateRange {
  desde: string | null; // YYYY-MM-DD
  hasta: string | null;
}

/** Filter values without action methods. */
export interface FilterValues {
  q: string;
  rango: DateRange;
  estados: string[];
  ccaas: string[];
  tecnologias: string[];
  importeMin: number | null;
  /**
   * "Sólo las que siguen abiertas" — descarta los estados terminales.
   *
   * No es lo mismo que `estados: ["PUB","EV"]`, y por eso existe: enumerar los
   * abiertos deja fuera cualquier código que la fuente publique después
   * (`ADM` es el caso real). El backend ya lo resolvía con `solo_abiertas`;
   * lo que faltaba era que el ámbito pudiera expresarlo, para que una tarjeta
   * que cuenta "activas" pueda abrir el listado que enseña justo esas.
   */
  soloAbiertas: boolean;
  /**
   * F1.1 — los tres filtros que sólo aplica el listado (`GET /licitaciones`):
   * código CODICE de procedimiento, provincia tal como la publica la fuente e
   * importe máximo. Opcionales porque ninguna pantalla analítica los consume
   * todavía: la barra de ámbito sólo los ofrece donde la página los declara
   * (`optInFilterKeys` en `lib/navigation.ts`).
   */
  procedimientos?: string[];
  provincias?: string[];
  importeMax?: number | null;
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
  if (filters.soloAbiertas) params.solo_abiertas = "true";
  if (filters.procedimientos?.length) params.procedimiento = filters.procedimientos.join(",");
  if (filters.provincias?.length) params.provincia = filters.provincias.join(",");
  if (filters.importeMax != null) params.importe_max = String(filters.importeMax);
  return params;
}

/** Forma de los `searchParams` que Next entrega a una página de servidor. */
export type SearchParamsServidor = Record<string, string | string[] | undefined>;

/**
 * Los parámetros de API que `useFilterParams()` calcularía para esta URL.
 *
 * Reproduce la lectura de `nuqs` (`parseAsString`: primer valor, cadena vacía
 * como ausencia) y la derivación de `useFilters`. Un test de paridad
 * (`lib/__tests__/filter-params.test.tsx`) compara las dos salidas sobre las
 * mismas URLs; si alguien añade un filtro a `filters.ts` y no aquí, falla.
 */
export function filterParamsFromSearch(
  search: URLSearchParams | SearchParamsServidor,
): Record<string, string> {
  const leer = (clave: string): string => {
    if (search instanceof URLSearchParams) return search.get(clave) ?? "";
    const valor = search[clave];
    return (Array.isArray(valor) ? valor[0] : valor) ?? "";
  };
  const lista = (clave: string): string[] => {
    const valor = leer(clave);
    return valor ? valor.split(",") : [];
  };
  const importe = leer("importe_min");
  const importeMax = leer("importe_max");
  return filtersToParams({
    q: leer("q"),
    rango: { desde: leer("fecha_desde") || null, hasta: leer("fecha_hasta") || null },
    estados: lista("estado"),
    ccaas: lista("ccaa"),
    tecnologias: lista("tecnologia"),
    importeMin: importe ? Number(importe) : null,
    soloAbiertas: leer("solo_abiertas") === "true",
    procedimientos: lista("procedimiento"),
    provincias: lista("provincia"),
    importeMax: importeMax ? Number(importeMax) : null,
  });
}
