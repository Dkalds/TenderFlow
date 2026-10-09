/**
 * Las dos series de Competidores que cruzan dimensiones: la matriz empresa ×
 * CCAA y el mapa de competidores con sus dos lentes.
 *
 * Van juntas porque comparten el modo de mentir: en un cruce, un cero por dato
 * ausente no se lee como «sin dato» sino como una posición —el punto pegado al
 * eje—, y eso es una afirmación que el dataset no hace. Aquí está decidido
 * dónde abstenerse.
 *
 * Son funciones puras sobre lo que la vista ya descargó (ADR-014).
 */

import { truncate } from "@/lib/utils";

import type { Competitor, HeatmapEntry, Lente } from "./competidores-types";
import { esVigilada } from "./vigilados";

/* ── Matriz empresa × CCAA ──────────────────────────────────────────── */

export interface HeatmapModel {
  empresas: string[];
  ccaas: string[];
  matrix: Record<string, Record<string, number>>;
  max: number;
}

const EMPTY_HEATMAP: HeatmapModel = { empresas: [], ccaas: [], matrix: {}, max: 0 };

/** Matriz empresa × CCAA, recortada a las 10 empresas con más contratos. */
export function buildHeatmap(entries: HeatmapEntry[] | undefined, search: string): HeatmapModel {
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

/* ── Mapa de competidores ───────────────────────────────────────────── */

export interface PuntoMapa {
  nombre: string;
  x: number;
  y: number;
  /** Cuota del importe: el tamaño del punto. */
  cuota: number;
  /** Nombre corto junto al punto, solo en los que destacan; vacío en el resto. */
  etiqueta: string;
  seleccionado: boolean;
  vigilada: boolean;
  /** Lo que el tooltip cuenta de la empresa, tal cual llegó. */
  empresa: Competitor;
}

export interface MapaModel {
  puntos: PuntoMapa[];
  /** Medianas de los puntos dibujados; `null` con menos de dos. */
  medianaX: number | null;
  medianaY: number | null;
  /** Cuántas empresas de la lista no traen las dos medidas de la lente. */
  sinDato: number;
}

/** Cuántos puntos llevan su nombre al lado, además de la abierta y las vigiladas. */
const ETIQUETAS_MAPA = 6;

function mediana(valores: number[]): number | null {
  if (valores.length < 2) return null;
  const ordenados = [...valores].sort((a, b) => a - b);
  const mitad = Math.floor(ordenados.length / 2);
  return ordenados.length % 2 === 0 ? (ordenados[mitad - 1] + ordenados[mitad]) / 2 : ordenados[mitad];
}

/**
 * Los dos ejes de un competidor en una lente, o `null` si le falta alguno.
 *
 * `importe_medio` y `n_organos` a 0 son el valor por defecto del backend, no
 * una medida: un punto en el origen afirmaría «contratos minúsculos» o «ningún
 * cliente», que el dataset no dice. Una baja media de 0 sí es un dato.
 */
function ejesDe(c: Competitor, lente: Lente): { x: number; y: number } | null {
  if (lente === "precio") {
    if (c.baja_media == null || c.importe_medio <= 0) return null;
    return { x: c.baja_media, y: c.importe_medio };
  }
  if (c.n_organos <= 0) return null;
  return { x: c.n_organos, y: c.pct_top_organo };
}

/**
 * El mapa de competidores: cada empresa es un punto en el plano de la lente.
 *
 * «Precio» cruza a qué baja gana con el tamaño de sus contratos; «Clientes», a
 * cuántos órganos adjudica con cuánto depende del primero. Las medianas de los
 * puntos dibujados parten el plano en cuatro perfiles.
 */
export function buildMapa(
  competitors: Competitor[],
  lente: Lente,
  marcas: { abierta: string | null; vigiladas: ReadonlySet<number> },
): MapaModel {
  const dibujables = competitors.flatMap((c) => {
    const ejes = ejesDe(c, lente);
    return ejes ? [{ c, ...ejes }] : [];
  });
  const destacadas = new Set(
    [...dibujables]
      .sort((a, b) => b.c.cuota - a.c.cuota)
      .slice(0, ETIQUETAS_MAPA)
      .map((d) => d.c.nombre),
  );
  const puntos = dibujables.map(({ c, x, y }) => {
    const seleccionado = c.nombre === marcas.abierta;
    const vigilada = esVigilada(c, marcas.vigiladas);
    return {
      nombre: c.nombre,
      x,
      y,
      cuota: c.cuota,
      etiqueta: seleccionado || vigilada || destacadas.has(c.nombre) ? truncate(c.nombre, 22) : "",
      seleccionado,
      vigilada,
      empresa: c,
    };
  });
  return {
    puntos,
    medianaX: mediana(puntos.map((p) => p.x)),
    medianaY: mediana(puntos.map((p) => p.y)),
    sinDato: competitors.length - puntos.length,
  };
}
