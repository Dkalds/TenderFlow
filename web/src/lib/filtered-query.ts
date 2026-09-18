/**
 * Clave y URL de una consulta con ámbito, sin React.
 *
 * Es la aritmética de `hooks/use-filtered-query.ts` sacada a un módulo puro
 * para que el prefetch en servidor (`lib/server-prefetch.ts`) construya
 * **exactamente** la misma clave y la misma URL que el hook pedirá en el
 * navegador. Una clave que difiera en un solo segmento hidrata una entrada de
 * caché que nadie lee: el servidor paga la petición y el cliente la repite.
 */

/** Parámetros explícitos fusionados con el ámbito; el ámbito gana. */
export function mergeFilteredParams(
  filterParams: Record<string, string>,
  extraParams?: Record<string, string>,
): Record<string, string> {
  return { ...extraParams, ...filterParams };
}

/**
 * La ruta puede traer ya su propia query (`…/trends?group_by=month`), así que
 * los filtros se FUSIONAN sobre ella en vez de concatenarse detrás de un
 * segundo `?`. Concatenar producía `…/trends?group_by=month?tecnologia=SAP`,
 * que el backend lee como `group_by="month?tecnologia=SAP"` y su
 * `Literal["month","week","day"]` rechaza con 422: la pantalla entera se caía
 * en cuanto el ámbito tenía un filtro (`/mercado?tecnologia=SAP`).
 */
export function filteredQueryUrl(url: string, merged: Record<string, string>): string {
  const [path, baseQuery = ""] = url.split("?");
  const search = new URLSearchParams(baseQuery);
  // Los params explícitos ganan a los literales de la ruta, misma precedencia
  // que `extraParams` ← `filterParams` de `mergeFilteredParams`.
  for (const [key, value] of Object.entries(merged)) search.set(key, value);
  const queryString = search.toString();
  return queryString ? `${path}?${queryString}` : path;
}

/**
 * La URL y los params fusionados forman parte de la key: dos endpoints (o el
 * mismo con distintos `extraParams`) comparten `baseKey` y colisionarían en
 * caché de otro modo. `baseKey` sigue siendo el prefijo, así que las
 * invalidaciones por prefijo (`invalidateQueries({ queryKey: baseKey })`)
 * siguen alcanzando todas las variantes.
 */
export function filteredQueryKey(
  baseKey: readonly string[],
  url: string,
  merged: Record<string, string>,
): unknown[] {
  return [...baseKey, url, merged];
}
