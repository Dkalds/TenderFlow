/**
 * Derivaciones de la pantalla de Competidores, fuera del árbol de render.
 *
 * `competidores/page.tsx` pasaba de las 1.000 líneas y traía once `useMemo`
 * encadenados —búsqueda, orden, tarta, barras, dispersión, mapa de calor, radar
 * comparativo, treemap, posicionamiento, estacionalidad y ranking de bajas—
 * dentro del componente. Cada uno tiene reglas que sí importan (qué cuenta como
 * «Otros», cómo se normaliza el radar, qué pasa cuando falta un dato) y ninguna
 * se puede comprobar sin montar siete gráficos `dynamic()` que en jsdom no
 * pintan nada. Aquí quedan como funciones puras.
 *
 * No hay fetch: reciben lo que la página ya descargó de `api/`. La agregación
 * sigue viniendo del backend; esto solo da forma a lo recibido para el gráfico.
 */
"use client";

import { useMemo } from "react";
import { truncate } from "@/lib/utils";

/* ── Tipos del contrato ─────────────────────────────────────────────── */

export interface Competitor {
  nombre: string;
  empresa_id?: number | null;
  nif?: string | null;
  empresa_ids?: number[];
  nifs?: string[];
  nombres_variantes?: string[];
  es_agrupacion?: boolean;
  count: number;
  importe: number;
  cuota: number;
  contratos_por_anio?: number;
  importe_medio?: number;
  baja_media?: number;
  n_organos?: number;
  ofertas_medias?: number;
  pct_monopolio?: number;
  pct_top_organo?: number;
  ultima?: string;
}

export interface HeatmapEntry {
  ccaa: string;
  empresa: string;
  count: number;
}

export interface BajaItem {
  grupo: string;
  grupo_id?: number;
  contratos: number;
  baja_media_pct: number | null;
}

export type SortKey =
  | "nombre"
  | "count"
  | "importe"
  | "cuota"
  | "contratos_por_anio"
  | "importe_medio"
  | "baja_media"
  | "nif"
  | "ofertas_medias"
  | "pct_monopolio"
  | "pct_top_organo"
  | "ultima";

/** Columnas cuyo valor es texto: se comparan con `localeCompare`, no restando. */
const TEXT_SORT_KEYS: ReadonlySet<SortKey> = new Set(["nombre", "nif", "ultima"]);

export const MONTH_LABELS = [
  "Ene",
  "Feb",
  "Mar",
  "Abr",
  "May",
  "Jun",
  "Jul",
  "Ago",
  "Sep",
  "Oct",
  "Nov",
  "Dic",
];

export const RADAR_DIMENSIONS = [
  "Contratos",
  "Importe",
  "Cuota",
  "Contratos/Año",
  "Importe Medio",
  "Agresividad baja",
] as const;

/* ── Búsqueda y orden ───────────────────────────────────────────────── */

export interface Searchable {
  nombre: string;
  nif?: string | null;
  nifs?: string[];
  nombres_variantes?: string[];
}

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

/* ── Series de gráfico ──────────────────────────────────────────────── */

export interface PieSlice {
  name: string;
  value: number;
}

/**
 * Tarta de cuota: top 10 por importe más un resto agregado.
 *
 * Sin búsqueda, «Otros» es el mercado total menos el top 10 —incluye la cola que
 * quedó fuera del `limit` que devolvió el backend—. Con búsqueda solo se puede
 * hablar de lo filtrado visible, así que «Otros» es la cola de ese subconjunto.
 */
export function buildPieData(
  filtered: Competitor[],
  search: string,
  importeTotal: number | undefined,
): PieSlice[] {
  if (!filtered.length) return [];
  const sorted = [...filtered].sort((a, b) => b.importe - a.importe);
  const top10 = sorted.slice(0, 10);
  const top10Importe = top10.reduce((s, c) => s + c.importe, 0);
  const otrosImporte = search
    ? sorted.slice(10).reduce((s, c) => s + c.importe, 0)
    : Math.max((importeTotal ?? top10Importe) - top10Importe, 0);
  const result: PieSlice[] = top10.map((c) => ({
    name: truncate(c.nombre, 25),
    value: c.importe,
  }));
  if (otrosImporte > 0) result.push({ name: "Otros", value: otrosImporte });
  return result;
}

/** Barras: los 20 competidores con más adjudicaciones. */
export function buildBarData(filtered: Competitor[]): Competitor[] {
  return [...filtered].sort((a, b) => b.count - a.count).slice(0, 20);
}

/** Nombres del top 5 por importe — son los únicos etiquetados en la dispersión. */
export function buildScatterTop5(competitors: Competitor[] | undefined): Set<string> {
  if (!competitors?.length) return new Set<string>();
  return new Set(
    [...competitors]
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 5)
      .map((c) => c.nombre),
  );
}

export interface HeatmapModel {
  empresas: string[];
  ccaas: string[];
  matrix: Record<string, Record<string, number>>;
  max: number;
}

const EMPTY_HEATMAP: HeatmapModel = { empresas: [], ccaas: [], matrix: {}, max: 0 };

/** Mapa de calor empresa × CCAA, recortado a las 10 empresas con más contratos. */
export function buildHeatmap(
  entries: HeatmapEntry[] | undefined,
  search: string,
): HeatmapModel {
  if (!entries?.length) return EMPTY_HEATMAP;
  const filtered = search
    ? entries.filter((h) => h.empresa.toLowerCase().includes(search.toLowerCase()))
    : entries;

  const empresaCounts: Record<string, number> = {};
  for (const h of filtered) {
    empresaCounts[h.empresa] = (empresaCounts[h.empresa] ?? 0) + h.count;
  }
  const empresas = Object.entries(empresaCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([e]) => e);
  const empresaSet = new Set(empresas);

  const ccaaSet = new Set<string>();
  const matrix: Record<string, Record<string, number>> = {};
  let max = 0;
  for (const h of filtered) {
    if (!empresaSet.has(h.empresa)) continue;
    ccaaSet.add(h.ccaa);
    if (!matrix[h.empresa]) matrix[h.empresa] = {};
    matrix[h.empresa][h.ccaa] = h.count;
    if (h.count > max) max = h.count;
  }
  return { empresas, ccaas: Array.from(ccaaSet).sort(), matrix, max };
}

export interface RadarModel {
  nameA: string;
  nameB: string;
  /** `value: null` = esa dimensión no existe para esa empresa. Ver abajo. */
  dataA: { dimension: string; value: number | null }[];
  dataB: { dimension: string; value: number | null }[];
}

/**
 * Radar de dos competidores, con cada eje normalizado al máximo del mercado.
 *
 * El denominador es el máximo de **todos** los competidores, no de los dos
 * elegidos: si no, comparar a dos rezagados los pintaría al 100% y el gráfico
 * mentiría sobre su tamaño. El `max(…, 1)` evita dividir por cero cuando una
 * métrica no viene en el dataset.
 */
export function buildRadarData(
  selectedCompanies: string[],
  competitors: Competitor[] | undefined,
): RadarModel | null {
  if (selectedCompanies.length !== 2 || !competitors) return null;
  const [nameA, nameB] = selectedCompanies;
  const compA = competitors.find((c) => c.nombre === nameA);
  const compB = competitors.find((c) => c.nombre === nameB);
  if (!compA || !compB) return null;

  const maxCount = Math.max(...competitors.map((c) => c.count), 1);
  const maxImporte = Math.max(...competitors.map((c) => c.importe), 1);
  const maxCuota = Math.max(...competitors.map((c) => c.cuota), 1);
  // fdi-allow:nulo-a-cero — techo de normalización: una empresa sin el dato no
  // debe subir el máximo del mercado, y `Math.max(…, 1)` ya evita el /0.
  const maxCpa = Math.max(...competitors.map((c) => c.contratos_por_anio ?? 0), 1);
  // fdi-allow:nulo-a-cero — ídem.
  const maxIm = Math.max(...competitors.map((c) => c.importe_medio ?? 0), 1);
  // fdi-allow:nulo-a-cero — ídem.
  const maxBaja = Math.max(...competitors.map((c) => c.baja_media ?? 0), 1);

  // Los ejes que la empresa no tiene salen `null`, no 0. En un radar de
  // comparación un 0 no es "sin dato": es el vértice pegado al centro, o sea
  // "el peor del mercado en esa dimensión". Recharts deja hueco con `null`,
  // que es exactamente lo que hay que comunicar.
  const escala = (valor: number | null | undefined, maximo: number): number | null =>
    valor == null ? null : (valor / maximo) * 100;

  const normalize = (c: Competitor): (number | null)[] => [
    (c.count / maxCount) * 100,
    (c.importe / maxImporte) * 100,
    (c.cuota / maxCuota) * 100,
    escala(c.contratos_por_anio, maxCpa),
    escala(c.importe_medio, maxIm),
    escala(c.baja_media, maxBaja),
  ];

  const valsA = normalize(compA);
  const valsB = normalize(compB);

  return {
    nameA,
    nameB,
    dataA: RADAR_DIMENSIONS.map((d, i) => ({ dimension: d, value: valsA[i] })),
    dataB: RADAR_DIMENSIONS.map((d, i) => ({ dimension: d, value: valsB[i] })),
  };
}

export interface TreemapNode {
  name: string;
  size: number;
  count: number;
  // El treemap de recharts indexa por clave arbitraria para el tooltip.
  [key: string]: string | number;
}

/** Treemap sectorial: top 20 por importe. */
export function buildTreemapData(filtered: Competitor[]): TreemapNode[] {
  if (!filtered.length) return [];
  return [...filtered]
    .sort((a, b) => b.importe - a.importe)
    .slice(0, 20)
    .map((c) => ({ name: truncate(c.nombre, 22), size: c.importe, count: c.count }));
}

export interface PositioningPoint {
  nombre: string;
  baja_media: number;
  importe_medio: number;
  count: number;
  /** `null` = el corpus no reporta ofertantes para esta empresa. Ver abajo. */
  pct_monopolio: number | null;
}

/**
 * Posicionamiento baja media × importe medio.
 *
 * Descarta a quien no tiene ambas métricas: un punto en (0,0) por dato ausente
 * se leería como «oferta a precio de catálogo y contratos minúsculos», que es
 * una afirmación que el dataset no hace.
 */
export function buildPositioningData(filtered: Competitor[]): PositioningPoint[] {
  if (!filtered.length) return [];
  return filtered
    .filter((c) => c.baja_media != null && c.importe_medio != null && c.importe_medio > 0)
    .map((c) => ({
      nombre: c.nombre,
      // Los dos ejes están garantizados por el `filter` de arriba; el `??` es
      // solo para el compilador.
      // El `filter` de arriba ya garantiza los dos ejes; el `??` es para el
      // compilador, no una coerción de dato ausente.
      baja_media: c.baja_media ?? 0, // fdi-allow:nulo-a-cero
      importe_medio: c.importe_medio ?? 0, // fdi-allow:nulo-a-cero
      count: c.count,
      // `pct_monopolio` NO se rellena con 0. Este módulo descartaba los puntos
      // sin ambos ejes precisamente para no afirmar «oferta a precio de
      // catálogo y contratos minúsculos», y luego hacía justo eso con la
      // tercera dimensión: una empresa sin dato de ofertantes salía en el
      // tooltip como «% Monopolio: 0,0 %», o sea como la más disputada del
      // mercado. `null` viaja hasta el tooltip, que lo pinta como sin dato.
      pct_monopolio: c.pct_monopolio ?? null,
    }));
}

export interface EstacionalidadPoint {
  mes: string;
  count: number;
  importe: number;
}

/** Rellena los doce meses: un mes sin datos vale cero, no se salta del eje. */
export function buildEstacionalidad(
  entries: { mes: number; count: number; importe: number }[] | undefined,
): EstacionalidadPoint[] {
  if (!entries?.length) return [];
  return Array.from({ length: 12 }, (_, i) => {
    const entry = entries.find((e) => e.mes === i + 1);
    return { mes: MONTH_LABELS[i], count: entry?.count ?? 0, importe: entry?.importe ?? 0 };
  });
}

export interface BajasModel {
  rows: BajaItem[];
  maxBaja: number;
}

/** Ranking de bajas: las doce más agresivas, y el máximo para la barra. */
export function sortBajas(items: BajaItem[] | undefined): BajasModel {
  const withValue = (items ?? []).filter((b) => b.baja_media_pct != null);
  const sorted = [...withValue].sort(
    // Clave de orden, no valor pintado: sin dato la fila cae al final en vez
    // de encabezar el ranking.
    (a, b) => (b.baja_media_pct ?? 0) - (a.baja_media_pct ?? 0), // fdi-allow:nulo-a-cero
  );
  // fdi-allow:nulo-a-cero — techo de normalización de la barra.
  const maxBaja = Math.max(...sorted.map((b) => b.baja_media_pct ?? 0), 1);
  return { rows: sorted.slice(0, 12), maxBaja };
}

/* ── Drill-down ─────────────────────────────────────────────────────── */

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

/* ── Hook agregador ─────────────────────────────────────────────────── */

export interface CompetidoresViewInput<S extends Searchable> {
  competitors: Competitor[] | undefined;
  scatterData: S[] | undefined;
  heatmapCcaa: HeatmapEntry[] | undefined;
  estacionalidad: { mes: number; count: number; importe: number }[] | undefined;
  importeTotal: number | undefined;
  bajas: BajaItem[] | undefined;
  search: string;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  selectedCompanies: string[];
}

export interface CompetidoresView<S extends Searchable> {
  filteredCompetitors: Competitor[];
  filteredSorted: Competitor[];
  pieData: PieSlice[];
  barData: Competitor[];
  scatterData: S[];
  scatterTop5: Set<string>;
  heatmapData: HeatmapModel;
  radarData: RadarModel | null;
  treemapData: TreemapNode[];
  positioningData: PositioningPoint[];
  estacionalidadData: EstacionalidadPoint[];
  bajasSorted: BajasModel;
}

/** Todas las series de la pantalla, memoizadas sobre los datos ya descargados. */
export function useCompetidoresView<S extends Searchable>({
  competitors,
  scatterData,
  heatmapCcaa,
  estacionalidad,
  importeTotal,
  bajas,
  search,
  sortKey,
  sortDir,
  selectedCompanies,
}: CompetidoresViewInput<S>): CompetidoresView<S> {
  const filteredCompetitors = useMemo(
    () => filterBySearch(competitors ?? [], search),
    [competitors, search],
  );

  const filteredSorted = useMemo(
    () => sortCompetitors(filteredCompetitors, sortKey, sortDir),
    [filteredCompetitors, sortKey, sortDir],
  );

  const pieData = useMemo(
    () => buildPieData(filteredCompetitors, search, importeTotal),
    [filteredCompetitors, search, importeTotal],
  );

  const barData = useMemo(() => buildBarData(filteredCompetitors), [filteredCompetitors]);

  const filteredScatter = useMemo(
    () => filterBySearch(scatterData ?? [], search),
    [scatterData, search],
  );

  const scatterTop5 = useMemo(() => buildScatterTop5(competitors), [competitors]);

  const heatmapData = useMemo(() => buildHeatmap(heatmapCcaa, search), [heatmapCcaa, search]);

  const radarData = useMemo(
    () => buildRadarData(selectedCompanies, competitors),
    [selectedCompanies, competitors],
  );

  const treemapData = useMemo(
    () => buildTreemapData(filteredCompetitors),
    [filteredCompetitors],
  );

  const positioningData = useMemo(
    () => buildPositioningData(filteredCompetitors),
    [filteredCompetitors],
  );

  const estacionalidadData = useMemo(
    () => buildEstacionalidad(estacionalidad),
    [estacionalidad],
  );

  const bajasSorted = useMemo(() => sortBajas(bajas), [bajas]);

  return {
    filteredCompetitors,
    filteredSorted,
    pieData,
    barData,
    scatterData: filteredScatter,
    scatterTop5,
    heatmapData,
    radarData,
    treemapData,
    positioningData,
    estacionalidadData,
    bajasSorted,
  };
}
