/**
 * Las nueve series de gráfico de Competidores, como funciones puras.
 *
 * No hay fetch: reciben lo que la vista ya descargó de `api/`. La agregación
 * sigue viniendo del backend (ADR-014); esto solo da forma a lo recibido.
 *
 * Cada builder tiene una regla que sí importa —qué cuenta como «Otros», contra
 * qué se normaliza el radar, a quién descarta el posicionamiento— y ninguna se
 * podría comprobar desde el árbol de render.
 */

import { truncate } from "@/lib/utils";

import type { BajaItem, Competitor, HeatmapEntry } from "./competidores-types";

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
