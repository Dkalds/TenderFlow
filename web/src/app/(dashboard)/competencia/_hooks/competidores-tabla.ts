/**
 * Búsqueda, orden, selección para comparar y drill-down: todo lo que gobierna
 * la **tabla** de Competidores, como funciones puras.
 *
 * Ninguna toca la red ni React: reciben lo que la vista ya descargó. Eso es lo
 * que permite comprobar las reglas que importan —qué identidades encuentra una
 * búsqueda, qué columnas se ordenan como texto, qué ids agrega el dossier— sin
 * montar siete gráficos `dynamic()` que en jsdom no pintan nada.
 */

import type { Competitor, Searchable, SortKey } from "./competidores-types";

/** Columnas cuyo valor es texto: se comparan con `localeCompare`, no restando. */
const TEXT_SORT_KEYS: ReadonlySet<SortKey> = new Set(["nombre", "nif", "ultima"]);

/**
 * Filtra por texto libre mirando también NIFs y variantes de nombre.
 *
 * Un competidor fusionado se busca por cualquiera de sus identidades: escribir
 * el NIF de una filial tiene que encontrar el grupo.
 */
export function filterBySearch<T extends Searchable>(items: T[], search: string): T[] {
  if (!search) return items;
  const q = search.toLowerCase();
  return items.filter((c) =>
    [c.nombre, c.nif, ...(c.nifs ?? []), ...(c.nombres_variantes ?? [])]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q),
  );
}

/** Ordena la tabla de competidores; texto por locale, el resto numérico. */
export function sortCompetitors(
  items: Competitor[],
  sortKey: SortKey,
  sortDir: "asc" | "desc",
): Competitor[] {
  const mul = sortDir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    if (TEXT_SORT_KEYS.has(sortKey)) {
      return mul * ((a[sortKey] ?? "") as string).localeCompare((b[sortKey] ?? "") as string);
    }
    return mul * (((a[sortKey] as number) ?? 0) - ((b[sortKey] as number) ?? 0));
  });
}

/** Selección para el radar: como mucho dos, la más antigua cede el sitio. */
export function toggleCompareSelection(prev: string[], nombre: string): string[] {
  if (prev.includes(nombre)) return prev.filter((n) => n !== nombre);
  if (prev.length >= 2) return [prev[1], nombre];
  return [...prev, nombre];
}

/**
 * Identidades del maestro que representan al mismo competidor analítico.
 *
 * El dossier siempre agrega todas —el usuario nunca elige cuál abrir—, así que
 * se deduplica `empresa_id` con `empresa_ids`.
 */
export function drillDownIds(company: Competitor | null): number[] {
  if (!company) return [];
  const ids = new Set<number>();
  if (company.empresa_id != null) ids.add(company.empresa_id);
  for (const id of company.empresa_ids ?? []) ids.add(id);
  return [...ids];
}

/** `empresa_ids` solo viaja cuando el grupo tiene más de una identidad. */
export function drillDownExtraParams(ids: number[]): Record<string, string> {
  return ids.length > 1 ? { empresa_ids: ids.join(",") } : {};
}
