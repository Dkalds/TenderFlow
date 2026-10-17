/**
 * La parte pura de la cola de cierre (`cola-cierre.tsx`): cuántas horas le
 * quedan a cada expediente, cuáles se enseñan y cuántas filas caben. Sin
 * React, para probarla sin montar la tarjeta.
 */

import type { LicitacionSummary } from "@/lib/api-types";

/** Filas mínimas: las que se ven en un teléfono, donde la tarjeta no se estira. */
export const VISIBLES = 4;

/** Alto de una fila (`h-10`). La cuenta de las que caben se hace con él. */
export const ALTO_FILA_PX = 40;

/** Cuántas filas enteras caben en `altoPx`, nunca menos de `minimo`. */
export function filasQueCaben(altoPx: number, minimo = VISIBLES): number {
  return Math.max(minimo, Math.floor(altoPx / ALTO_FILA_PX));
}

/** La ventana de la cola, en horas: el 100 % de la barra de cada fila. */
export const VENTANA_HORAS = 48;

export interface FilaCierre {
  id: string;
  titulo: string;
  organo: string;
  importe: number | null;
  horas: number;
}

/**
 * Horas completas hasta `limite` desde `ahora`, o `null` si la fecha no se
 * puede leer. El redondeo es la parte que engaña: lo fija su test.
 */
export function horasRestantes(limite: string | null | undefined, ahora: number): number | null {
  if (!limite) return null;
  const ms = Date.parse(limite);
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.floor((ms - ahora) / 3_600_000));
}

/**
 * Las horas que quedan a cada expediente traído, para el reloj. Solo las que
 * caen dentro de la ventana: la petición corta por día y trae algún cierre de
 * más allá de las 48 horas.
 */
export function horasEnVentana(items: LicitacionSummary[], ahora: number): number[] {
  return items
    .map((item) => horasRestantes(item.fecha_limite, ahora))
    .filter((horas): horas is number => horas !== null && horas <= VENTANA_HORAS);
}

/** Ordena por plazo ascendente y recorta a las que caben. */
export function proximasACerrar(
  items: LicitacionSummary[],
  ahora: number,
  visibles = VISIBLES,
): FilaCierre[] {
  return items
    .map((item) => ({
      id: item.id_externo,
      titulo: item.titulo ?? item.id_externo,
      organo: item.organo_contratacion ?? "—",
      importe: item.importe ?? null,
      horas: horasRestantes(item.fecha_limite, ahora),
    }))
    .filter((fila): fila is FilaCierre => fila.horas !== null)
    .sort((a, b) => a.horas - b.horas)
    .slice(0, visibles);
}
