/**
 * Las series de Competidores, como funciones puras.
 *
 * No hay fetch: reciben lo que la vista ya descargó de `api/`. La agregación
 * sigue viniendo del backend (ADR-014); esto solo da forma a lo recibido
 * —ordenar, recortar, escalar una barra contra el máximo visible— y, donde suma
 * algo, suma cifras que la API ya calculó sobre el ámbito entero.
 *
 * Cada builder tiene una regla que sí importa —qué cuenta como «Otras», cuándo
 * una concentración es parcial, qué es un dato y qué una ausencia— y ninguna se
 * podría comprobar desde el árbol de render.
 *
 * Las dos series que cruzan dimensiones (la matriz empresa × CCAA y el mapa de
 * competidores) viven en `competidores-cruces.ts`.
 */

import type { Competitor, EstacionalidadEntry, Metrica } from "./competidores-types";

export const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

/** Los totales del ámbito que acompañan a la lista; `null` = la API no los dio. */
export interface TotalesAmbito {
  totalAdjudicaciones: number | null;
  totalEmpresas: number | null;
}

/* ── Orden y cuota ──────────────────────────────────────────────────── */

export function ordenarPorMetrica(items: Competitor[], metrica: Metrica): Competitor[] {
  const valor = metrica === "importe" ? (c: Competitor) => c.importe : (c: Competitor) => c.count;
  return [...items].sort((a, b) => valor(b) - valor(a));
}

/**
 * Cuota de un competidor en la medida activa.
 *
 * Por importe es la que manda la API. Por adjudicaciones no hay campo: es su
 * recuento sobre el total del ámbito, las dos cifras de la API; sin ese total
 * no se calcula contra la suma de lo recibido, que daría la cuota entre los
 * primeros de la lista y no la del mercado.
 */
export function cuotaDe(c: Competitor, metrica: Metrica, totalAdjudicaciones: number | null): number | null {
  if (metrica === "importe") return c.cuota;
  if (totalAdjudicaciones == null || totalAdjudicaciones <= 0) return null;
  return (c.count / totalAdjudicaciones) * 100;
}

/* ── Concentración del titular ──────────────────────────────────────── */

export interface Concentracion {
  /** Cuota conjunta de las `n` primeras; `null` si no se puede afirmar. */
  pct: number | null;
  /** Cuántas empresas entran en la cifra (menos de las pedidas si no hay más). */
  n: number;
  /** La cifra sale de una lista recortada y puede quedarse corta. */
  parcial: boolean;
}

/** Cuántas empresas nombra el titular. */
export const EMPRESAS_TITULAR = 5;

/**
 * «5 empresas se reparten el 45 %»: la suma de las cuotas de las primeras.
 *
 * Es parcial por importe cuando la API no devolvió todas las empresas: la lista
 * llega ordenada por adjudicaciones, así que una empresa con pocos contratos
 * muy grandes puede haberse quedado fuera del corte. Por adjudicaciones ese
 * riesgo no existe.
 */
export function buildConcentracion(
  competitors: Competitor[],
  metrica: Metrica,
  totales: TotalesAmbito,
  n = EMPRESAS_TITULAR,
): Concentracion {
  const primeras = ordenarPorMetrica(competitors, metrica).slice(0, n);
  if (primeras.length === 0) return { pct: null, n: 0, parcial: false };
  if (metrica === "importe") {
    return {
      pct: primeras.reduce((suma, c) => suma + c.cuota, 0),
      n: primeras.length,
      parcial: totales.totalEmpresas != null && totales.totalEmpresas > competitors.length,
    };
  }
  const total = totales.totalAdjudicaciones;
  return {
    // Un solo cociente sobre la suma de recuentos, y no la suma de cocientes:
    // misma cifra, sin el arrastre de decimales de cada división.
    pct: total != null && total > 0 ? (primeras.reduce((suma, c) => suma + c.count, 0) / total) * 100 : null,
    n: primeras.length,
    parcial: false,
  };
}

/* ── Reparto en barra al 100 % ──────────────────────────────────────── */

export interface TramoReparto {
  nombre: string;
  pct: number;
  /** El resto del mercado: va en `chart-8` y no abre ningún perfil. */
  esOtros: boolean;
  seleccionado: boolean;
}

/** Cuántas empresas llevan nombre en la barra de reparto. */
export const EMPRESAS_REPARTO = 8;

/** Por debajo de esto el resto no se dibuja: es redondeo, no mercado. */
const RESTO_MINIMO = 0.05;

/**
 * Las primeras con nombre y el resto del mercado en un solo tramo.
 *
 * «Otras» es lo que falta hasta 100, no la suma de la cola recibida: incluye a
 * las empresas que quedaron fuera del `limit` de la API.
 */
export function buildReparto(
  competitors: Competitor[],
  metrica: Metrica,
  totales: TotalesAmbito,
  abierta: string | null,
  n = EMPRESAS_REPARTO,
): TramoReparto[] {
  const tramos: TramoReparto[] = [];
  for (const c of ordenarPorMetrica(competitors, metrica).slice(0, n)) {
    const pct = cuotaDe(c, metrica, totales.totalAdjudicaciones);
    if (pct == null) return [];
    tramos.push({ nombre: c.nombre, pct, esOtros: false, seleccionado: c.nombre === abierta });
  }
  if (tramos.length === 0) return [];

  const resto = 100 - tramos.reduce((suma, t) => suma + t.pct, 0);
  if (resto > RESTO_MINIMO) {
    const otras = totales.totalEmpresas != null ? totales.totalEmpresas - tramos.length : 0;
    tramos.push({
      nombre: otras > 0 ? `Otras ${otras} empresas` : "Otras empresas",
      pct: resto,
      esOtros: true,
      seleccionado: false,
    });
  }
  return tramos;
}

/* ── Meses del año ──────────────────────────────────────────────────── */

export interface EstacionalidadPoint {
  mes: string;
  count: number;
  importe: number;
}

/** Rellena los doce meses: un mes sin datos vale cero, no se salta del eje. */
export function buildEstacionalidad(entries: EstacionalidadEntry[] | undefined): EstacionalidadPoint[] {
  if (!entries?.length) return [];
  return Array.from({ length: 12 }, (_, i) => {
    const entry = entries.find((e) => e.mes === i + 1);
    return { mes: MONTH_LABELS[i], count: entry?.count ?? 0, importe: entry?.importe ?? 0 };
  });
}

/** El mes con más adjudicaciones; `null` si ninguno tiene actividad. */
export function mesPico(meses: EstacionalidadPoint[]): { indice: number; count: number } | null {
  let pico: { indice: number; count: number } | null = null;
  meses.forEach((mes, indice) => {
    if (mes.count > 0 && (pico == null || mes.count > pico.count)) pico = { indice, count: mes.count };
  });
  return pico;
}

/* ── Escalas del ranking ────────────────────────────────────────────── */

export interface EscalasRanking {
  cuota: number | null;
  baja: number | null;
  ofertas: number | null;
}

function maximo(valores: (number | null | undefined)[]): number | null {
  const medidos = valores.filter((v): v is number => v != null);
  return medidos.length > 0 ? Math.max(...medidos) : null;
}

/**
 * El tope de cada dibujo del ranking, entre las filas visibles.
 *
 * Una medida que ninguna fila trae no tiene escala (`null`), y su columna se
 * queda sin barra: un tope de 0 las pintaría todas vacías, como si se hubiera
 * medido y nadie bajara el precio.
 */
export function escalasRanking(filas: Competitor[]): EscalasRanking {
  return {
    cuota: maximo(filas.map((c) => c.cuota)),
    baja: maximo(filas.map((c) => c.baja_media)),
    ofertas: maximo(filas.map((c) => c.ofertas_medias)),
  };
}

/* ── Cara a cara ────────────────────────────────────────────────────── */

export type MedidaDuelo =
  | "cuota"
  | "count"
  | "importe_medio"
  | "baja_media"
  | "ofertas_medias"
  | "pct_monopolio"
  | "n_organos"
  | "pct_top_organo";

export interface FilaDuelo {
  clave: MedidaDuelo;
  /** `null` = esa empresa no trae la medida. */
  a: number | null;
  b: number | null;
  /** Ancho del ala, a escala del mayor de los dos. */
  pctA: number;
  pctB: number;
  /** Cuál de las dos cifras es la mayor. Con un empate o un dato ausente, ninguna. */
  mayorA: boolean;
  mayorB: boolean;
}

/** Un 0 que es el valor por defecto del backend, no una medida. */
const positivo = (valor: number): number | null => (valor > 0 ? valor : null);

const MEDIDAS_DUELO: { clave: MedidaDuelo; valor: (c: Competitor) => number | null }[] = [
  { clave: "cuota", valor: (c) => c.cuota },
  { clave: "count", valor: (c) => c.count },
  { clave: "importe_medio", valor: (c) => positivo(c.importe_medio) },
  { clave: "baja_media", valor: (c) => c.baja_media ?? null },
  { clave: "ofertas_medias", valor: (c) => c.ofertas_medias ?? null },
  { clave: "pct_monopolio", valor: (c) => c.pct_monopolio ?? null },
  { clave: "n_organos", valor: (c) => positivo(c.n_organos) },
  // Sin órganos no hay «primer cliente» del que medir el peso.
  { clave: "pct_top_organo", valor: (c) => (c.n_organos > 0 ? c.pct_top_organo : null) },
];

/**
 * Dos empresas, ocho medidas, cada una a escala del mayor de los dos.
 *
 * No se normaliza contra el mercado: aquí la pregunta es cuál de las dos es más
 * grande en cada medida, y la cifra exacta va escrita al lado de la barra.
 */
export function buildDuelo(a: Competitor, b: Competitor): FilaDuelo[] {
  return MEDIDAS_DUELO.map(({ clave, valor }) => {
    const va = valor(a);
    const vb = valor(b);
    const tope = Math.max(va ?? Number.NEGATIVE_INFINITY, vb ?? Number.NEGATIVE_INFINITY);
    const ancho = (v: number | null) => (v == null || tope <= 0 ? 0 : (v / tope) * 100);
    const comparables = va != null && vb != null;
    return {
      clave,
      a: va,
      b: vb,
      pctA: ancho(va),
      pctB: ancho(vb),
      mayorA: comparables && va > vb,
      mayorB: comparables && vb > va,
    };
  });
}

/* ── Qué empresa queda abierta ──────────────────────────────────────── */

/**
 * El perfil arranca abierto con la primera del ranking. Cerrarlo es una decisión
 * aparte de «ninguna elegida», porque sin ella el cierre volvería a abrir la
 * primera; y una elegida que ya no está en la lista (cambió el ámbito o la
 * búsqueda) cede el sitio a la primera en vez de dejar el perfil en blanco.
 */
export function resolverAbierta(
  ordenados: Competitor[],
  seleccion: string | null,
  cerrado: boolean,
): Competitor | null {
  if (cerrado) return null;
  return ordenados.find((c) => c.nombre === seleccion) ?? ordenados[0] ?? null;
}

/** La segunda empresa del cara a cara: distinta de la abierta y presente en los datos. */
export function resolverRival(
  competitors: Competitor[],
  rival: string | null,
  abierta: Competitor | null,
): Competitor | null {
  if (rival == null || abierta == null || rival === abierta.nombre) return null;
  return competitors.find((c) => c.nombre === rival) ?? null;
}
