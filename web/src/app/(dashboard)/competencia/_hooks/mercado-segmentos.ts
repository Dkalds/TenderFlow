/**
 * Lecturas del mercado por segmento: concentración (HHI), cuota y bajas.
 *
 * Funciones puras sobre las respuestas de `/competitive/hhi`, `/cuota`,
 * `/bajas` y `/bajas/referencia`, para poder probarlas sin red. Las peticiones
 * están en `use-mercado-segmentos.ts`.
 *
 * Aquí viven también los umbrales del HHI. Eran constantes de
 * `competidores-cifras.tsx` y ahora los usan dos bloques —la cifra del ámbito
 * y la lista de segmentos—; con una copia en cada uno, un segmento podía
 * salir «moderado» en una y «concentrado» en la otra con el mismo índice. Son
 * los que documenta el backend (`services/competitive/mercado.py`,
 * `concentracion_hhi`) y el glosario (`lib/glosario.ts`, `hhi`).
 */

import type { Schemas } from "@/lib/api-types";
import { cpvFamilyLabel } from "@/components/competitors/company-profile-types";

export type HhiSegmento = Schemas["HhiSegmento"];
export type CuotaEmpresa = Schemas["CuotaEmpresa"];
export type BajaAgregada = Schemas["BajaAgregada"];

/* ── HHI ──────────────────────────────────────────────────────────────── */

/** Los dos umbrales del índice, los habituales en defensa de la competencia. */
export const HHI_MODERADO = 1500;
export const HHI_CONCENTRADO = 2500;

export type ZonaHhi = "competitivo" | "moderado" | "concentrado";

export const ZONAS_HHI: readonly ZonaHhi[] = ["competitivo", "moderado", "concentrado"];

export function zonaHhi(hhi: number): ZonaHhi {
  if (hhi < HHI_MODERADO) return "competitivo";
  if (hhi < HHI_CONCENTRADO) return "moderado";
  return "concentrado";
}

const ETIQUETA_ZONA: Record<ZonaHhi, string> = {
  competitivo: "Mercado competitivo",
  moderado: "Concentración moderada",
  concentrado: "Mercado concentrado",
};

export function etiquetaHhi(hhi: number): string {
  return ETIQUETA_ZONA[zonaHhi(hhi)];
}

/* ── Segmentos ────────────────────────────────────────────────────────── */

/** Los cortes que admite `/competitive/hhi` (`segment_by`). */
export type SegmentoPor = "cpv" | "ccaa" | "organo" | "tecnologia";

export const OPCIONES_SEGMENTO: readonly { value: SegmentoPor; label: string }[] = [
  { value: "cpv", label: "Familia CPV" },
  { value: "ccaa", label: "Comunidad" },
  { value: "organo", label: "Órgano" },
  { value: "tecnologia", label: "Tecnología" },
];

/** Orden de la lista: el de la API (más concentrado primero) o por importe. */
export type OrdenSegmentos = "concentracion" | "importe";

export function ordenarSegmentos(items: readonly HhiSegmento[], orden: OrdenSegmentos): HhiSegmento[] {
  if (orden === "concentracion") return [...items];
  return [...items].sort((a, b) => b.importe_total - a.importe_total);
}

/**
 * El nombre legible de un segmento. Por CPV llega la división (dos dígitos,
 * `substr(cpv, 1, 2)` en el backend) y se nombra con la misma tabla que el
 * perfil de empresa.
 */
export function nombreSegmento(por: SegmentoPor, segmento: string | null | undefined): string {
  if (!segmento) return "Sin identificar";
  if (por === "cpv") return `${segmento} · ${cpvFamilyLabel(segmento)}`;
  return segmento;
}

/** Las consultas que se pueden hacer sobre un segmento elegido. */
export interface ConsultasDeSegmento {
  /** Parámetros de `/competitive/cuota`, o `null` si ese corte no la admite. */
  cuota: { cpv?: string; ccaa?: string } | null;
  /** Parámetros de `/competitive/bajas/referencia`, o `null` si no la admite. */
  referencia: { cpv?: string; organo?: string } | null;
}

/** `max_length` de los parámetros en `api/routes/competitive.py`. */
const MAX_CCAA_CUOTA = 50;
const MAX_ORGANO_REFERENCIA = 300;
const MAX_CPV = 8;

/**
 * Qué puede responder la API de un segmento concreto.
 *
 * Cada endpoint filtra por lo suyo: la cuota acepta CPV o comunidad, la baja
 * de referencia CPV u órgano, y ninguno de los dos acepta tecnología. Se dice
 * qué falta en vez de pedir con un parámetro que el endpoint ignoraría y
 * pintar la cifra de todo el mercado como si fuera la del segmento. Un valor
 * más largo que el `max_length` de la ruta tampoco se pide: sería un 422.
 */
export function consultasDeSegmento(por: SegmentoPor, segmento: string | null | undefined): ConsultasDeSegmento {
  if (!segmento) return { cuota: null, referencia: null };
  switch (por) {
    case "cpv":
      return segmento.length <= MAX_CPV
        ? { cuota: { cpv: segmento }, referencia: { cpv: segmento } }
        : { cuota: null, referencia: null };
    case "ccaa":
      return { cuota: segmento.length <= MAX_CCAA_CUOTA ? { ccaa: segmento } : null, referencia: null };
    case "organo":
      return {
        cuota: null,
        referencia: segmento.length <= MAX_ORGANO_REFERENCIA ? { organo: segmento } : null,
      };
    case "tecnologia":
      return { cuota: null, referencia: null };
  }
}

/* ── Bajas ────────────────────────────────────────────────────────────── */

/** Los cortes de `/competitive/bajas` que ofrece el bloque. */
export type BajasPor = "organo" | "cpv" | "ccaa";

/**
 * Sin `empresa` a propósito: la baja media por empresa ya es una columna del
 * ranking de esta misma pantalla, y repetirla en otra tabla son dos cifras
 * para la misma pregunta.
 */
export const OPCIONES_BAJAS: readonly { value: BajasPor; label: string }[] = [
  { value: "organo", label: "Órgano" },
  { value: "cpv", label: "Familia CPV" },
  { value: "ccaa", label: "Comunidad" },
];

/** Filtros de la barra global que `/competitive/bajas` entiende, con su nombre en la API. */
const FILTROS_DE_BAJAS = ["ccaa", "fecha_desde", "fecha_hasta", "importe_min"] as const;

/** Cómo se llama en la barra cada filtro que `/bajas` no aplica. */
const FILTROS_IGNORADOS: Record<string, string> = {
  q: "texto",
  estado: "estado",
  tecnologia: "tecnología",
  solo_abiertas: "solo abiertas",
  procedimiento: "procedimiento",
  provincia: "provincia",
  importe_max: "importe máximo",
};

/** Los parámetros de `/bajas` que salen de la barra global (`useFilterParams`). */
export function parametrosBajas(filtros: Readonly<Record<string, string>>): Record<string, string> {
  const salida: Record<string, string> = {};
  for (const clave of FILTROS_DE_BAJAS) {
    const valor = filtros[clave];
    if (valor) salida[clave] = valor;
  }
  return salida;
}

/**
 * Los filtros activos de la barra que `/bajas` no aplica, por su nombre.
 *
 * El resto de la pantalla los respeta; si este bloque los ignorara en
 * silencio, su tabla parecería del mismo ámbito que el ranking sin serlo.
 */
export function filtrosNoAplicados(filtros: Readonly<Record<string, string>>): string[] {
  return Object.keys(FILTROS_IGNORADOS)
    .filter((clave) => Boolean(filtros[clave]))
    .map((clave) => FILTROS_IGNORADOS[clave]);
}

/** Escala común de los rangos de baja: de lo más bajo (o 0) a lo más alto. */
export function escalaBajas(items: readonly BajaAgregada[]): { min: number; max: number } {
  let min = 0;
  let max = 0;
  for (const item of items) {
    if (item.baja_min_pct != null) min = Math.min(min, item.baja_min_pct);
    if (item.baja_max_pct != null) max = Math.max(max, item.baja_max_pct);
  }
  return { min, max: max > min ? max : min + 1 };
}

/** Posición (0-100) de una baja sobre la escala. */
export function posicionEnEscala(valor: number, escala: { min: number; max: number }): number {
  const pct = ((valor - escala.min) / (escala.max - escala.min)) * 100;
  return Math.max(0, Math.min(100, pct));
}

/**
 * Lo que significa la `base` de importe sobre la que se calcularon las bajas
 * (C1.1, ADR-032). Sin decirlo, una baja del 21 % podría ser exactamente el IVA.
 */
export function textoBase(base: string | null | undefined): string {
  if (base === "sin_iva") return "Calculadas solo sobre presupuestos con base sin IVA declarada.";
  if (base === "mixta") {
    return "Base mixta: se excluye lo que se sabe que lleva IVA, pero el histórico sin base declarada sigue dentro.";
  }
  return "Sin base de importe declarada.";
}
